"""PG-backed user store with JSON fallback (V1.0 Sprint 1).

When PostgreSQL is available (DATABASE_URL_SYNC or DATABASE_URL env set),
user authentication reads from the `users` table instead of the in-memory
DEMO_USERS dict. When PG is not available (demo/test mode without docker),
it gracefully falls back to DEMO_USERS — ensuring zero regression.

Design:
  - get_user(username) → dict | None  (tries PG first, falls back to DEMO_USERS)
  - authenticate(username, password) → dict | None  (bcrypt verify against PG or DEMO_USERS)
  - update_last_login(username) → None  (PG only, no-op in fallback mode)
  - is_pg_available() → bool  (check if PG engine can connect)
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Lazy-initialized PG engine (only created when first needed)
_pg_engine = None
_pg_available: Optional[bool] = None


def _get_sync_db_url() -> str:
    """Get the sync database URL from environment."""
    return (
        os.environ.get("DATABASE_URL_SYNC")
        or os.environ.get("DATABASE_URL", "").replace("+asyncpg", "+psycopg2")
        or "postgresql+psycopg2://seewo:seewo@localhost:5432/seewo"
    )


def is_pg_available() -> bool:
    """Check if PostgreSQL is reachable. Cached after first check."""
    global _pg_available, _pg_engine
    if _pg_available is not None:
        return _pg_available

    db_url = _get_sync_db_url()
    # SQLite is always available (for testing)
    if db_url.startswith("sqlite"):
        _pg_available = True
        return True

    try:
        _pg_engine = create_engine(db_url, pool_pre_ping=True, pool_size=2)
        with _pg_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _pg_available = True
        logger.info("PG user store: connected to %s", db_url.split("@")[-1] if "@" in db_url else "db")
    except Exception as e:
        _pg_available = False
        _pg_engine = None
        logger.info("PG user store: unavailable (%s), falling back to DEMO_USERS", type(e).__name__)

    return _pg_available


def _get_pg_engine():
    """Get or create the PG engine."""
    global _pg_engine
    if _pg_engine is None and is_pg_available():
        if _pg_engine is None:
            _pg_engine = create_engine(_get_sync_db_url(), pool_pre_ping=True, pool_size=2)
    return _pg_engine


def get_user(username: str) -> Optional[dict]:
    """Look up a user by username. Tries PG first, falls back to DEMO_USERS."""
    if is_pg_available():
        try:
            from infra.pg.orm import User
            engine = _get_pg_engine()
            with Session(engine) as session:
                user = session.execute(
                    select(User).where(User.username == username)
                ).scalar_one_or_none()
                if user:
                    return {
                        "user_id": user.username,
                        "username": user.username,
                        "name": user.display_name or user.username,
                        "role": user.role,
                        "password_hash": user.password_hash,
                        "student_id": user.username if user.role == "student" else None,
                        "avatar_color": user.avatar_color,
                        "level": user.student_level,
                        "consent_given": getattr(user, "consent_given", False),
                        "db_id": user.id,
                    }
        except Exception as e:
            logger.warning("PG user lookup failed for %s: %s, falling back", username, e)

    # Fallback to DEMO_USERS
    from security import DEMO_USERS
    user = DEMO_USERS.get(username)
    if not user:
        return None
    return {"user_id": username, "username": username, **user}


def authenticate(username: str, password: str, verify_fn) -> Optional[dict]:
    """Authenticate a user. Uses verify_fn(password, hash) for password checking.
    
    verify_fn is passed in to avoid circular import with security.py 
    (which has _verify_password).
    """
    user = get_user(username)
    if not user:
        return None
    if not verify_fn(password, user.get("password_hash", "")):
        return None
    return user


def update_last_login(username: str) -> None:
    """Update last_login_at in PG. No-op in fallback mode."""
    if not is_pg_available():
        return
    try:
        from infra.pg.orm import User
        from datetime import datetime
        engine = _get_pg_engine()
        with Session(engine) as session:
            user = session.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            if user:
                user.last_login_at = datetime.utcnow()
                session.commit()
    except Exception as e:
        logger.warning("Failed to update last_login for %s: %s", username, e)


def list_all_users() -> list[dict]:
    """List all users (for admin views). Tries PG, falls back to DEMO_USERS."""
    if is_pg_available():
        try:
            from infra.pg.orm import User
            engine = _get_pg_engine()
            with Session(engine) as session:
                users = session.execute(select(User)).scalars().all()
                return [
                    {
                        "user_id": u.username,
                        "username": u.username,
                        "name": u.display_name or u.username,
                        "role": u.role,
                        "avatar_color": u.avatar_color,
                        "level": u.student_level,
                    }
                    for u in users
                ]
        except Exception as e:
            logger.warning("PG list users failed: %s, falling back", e)

    from security import DEMO_USERS
    return [{"user_id": k, "username": k, **v} for k, v in DEMO_USERS.items()]


def reset_pg_cache() -> None:
    """Reset the PG availability cache (for testing)."""
    global _pg_available, _pg_engine
    _pg_available = None
    _pg_engine = None


# ── Sprint 4 P0-3: 家长知情同意 ──────────────────────────────────────

def set_consent(username: str) -> bool:
    """Mark a user as having given parental consent (PG only).

    Returns True on success, False if PG unavailable or user not found.
    """
    if not is_pg_available():
        return False
    try:
        from infra.pg.orm import User
        engine = _get_pg_engine()
        with Session(engine) as session:
            user = session.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            if user:
                user.consent_given = True
                session.commit()
                return True
        return False
    except Exception as e:
        logger.warning("Failed to set consent for %s: %s", username, e)
        return False


# ── Sprint 4 P0-2: 数据删除/导出 ──────────────────────────────────────

def delete_student_data(student_id: str) -> dict:
    """Delete all data associated with a student (submissions, corrections, analytics).

    Works on both PG (if available) and JSON storage paths.
    Returns a summary dict: {deleted_submissions, deleted_corrections, deleted_analytics, storage}
    """
    summary = {"deleted_submissions": 0, "deleted_corrections": 0, "deleted_analytics": 0, "storage": "json"}

    # --- PG path ---
    if is_pg_available():
        try:
            from infra.pg.orm import User, Submission, Correction, AnalyticsSnapshot
            engine = _get_pg_engine()
            with Session(engine) as session:
                user = session.execute(
                    select(User).where(User.username == student_id)
                ).scalar_one_or_none()
                if user:
                    # Delete submissions
                    subs = session.execute(
                        select(Submission).where(Submission.student_id == user.id)
                    ).scalars().all()
                    for s in subs:
                        session.delete(s)
                    summary["deleted_submissions"] = len(subs)

                    # Delete corrections
                    corrs = session.execute(
                        select(Correction).where(Correction.student_id == user.id)
                    ).scalars().all()
                    for c in corrs:
                        session.delete(c)
                    summary["deleted_corrections"] = len(corrs)

                    # Delete analytics snapshots
                    snaps = session.execute(
                        select(AnalyticsSnapshot).where(AnalyticsSnapshot.student_id == user.id)
                    ).scalars().all()
                    for s in snaps:
                        session.delete(s)
                    summary["deleted_analytics"] = len(snaps)

                    session.commit()
            summary["storage"] = "pg"
            return summary
        except Exception as e:
            logger.warning("PG delete failed for %s: %s, falling back to JSON", student_id, e)

    # --- JSON fallback path ---
    import json as _json
    _data_dir = os.path.join(os.path.dirname(__file__), "data")

    # Delete from answers.json (submissions)
    answers_path = os.path.join(_data_dir, "answers.json")
    try:
        with open(answers_path, "r", encoding="utf-8") as f:
            answers = _json.load(f)
        keys_to_delete = [k for k, v in answers.items() if v.get("student_id") == student_id]
        for k in keys_to_delete:
            del answers[k]
        summary["deleted_submissions"] = len(keys_to_delete)
        with open(answers_path, "w", encoding="utf-8") as f:
            _json.dump(answers, f, ensure_ascii=False, indent=2)
    except (FileNotFoundError, _json.JSONDecodeError):
        pass

    # Delete from corrections.json
    corrections_path = os.path.join(_data_dir, "corrections.json")
    try:
        with open(corrections_path, "r", encoding="utf-8") as f:
            corrections = _json.load(f)
        for hw_key in list(corrections.keys()):
            hw_corrections = corrections[hw_key]
            sub_keys_to_delete = [
                sk for sk, rec in hw_corrections.items()
                if rec.get("student_id") == student_id
            ]
            for sk in sub_keys_to_delete:
                del hw_corrections[sk]
            summary["deleted_corrections"] += len(sub_keys_to_delete)
        with open(corrections_path, "w", encoding="utf-8") as f:
            _json.dump(corrections, f, ensure_ascii=False, indent=2)
    except (FileNotFoundError, _json.JSONDecodeError):
        pass

    # Delete analytics snapshots (growth_report, student_dashboard, knowledge_tree)
    for fname in ("growth_report.json", "student_dashboard.json", "knowledge_tree.json"):
        fpath = os.path.join(_data_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = _json.load(f)
            if isinstance(data, dict) and student_id in data:
                del data[student_id]
                with open(fpath, "w", encoding="utf-8") as f:
                    _json.dump(data, f, ensure_ascii=False, indent=2)
                summary["deleted_analytics"] += 1
        except (FileNotFoundError, _json.JSONDecodeError):
            pass

    summary["storage"] = "json"
    return summary


def export_student_data(student_id: str) -> dict:
    """Export all data associated with a student as a JSON-serializable dict.

    Works on both PG (if available) and JSON storage paths.
    Returns a dict with student profile, submissions, corrections, and analytics.
    """
    export: dict = {"student_id": student_id, "submissions": [], "corrections": [], "analytics": {}}

    # --- PG path ---
    if is_pg_available():
        try:
            from infra.pg.orm import User, Submission, Correction, AnalyticsSnapshot
            engine = _get_pg_engine()
            with Session(engine) as session:
                user = session.execute(
                    select(User).where(User.username == student_id)
                ).scalar_one_or_none()
                if user:
                    export["profile"] = {
                        "username": user.username,
                        "display_name": user.display_name,
                        "role": user.role,
                        "consent_given": getattr(user, "consent_given", False),
                        "created_at": str(user.created_at) if user.created_at else None,
                        "last_login_at": str(user.last_login_at) if user.last_login_at else None,
                    }

                    subs = session.execute(
                        select(Submission).where(Submission.student_id == user.id)
                    ).scalars().all()
                    for s in subs:
                        export["submissions"].append({
                            "submission_key": s.submission_key,
                            "answers": s.answers,
                            "submitted_at": str(s.submitted_at) if s.submitted_at else None,
                        })

                    corrs = session.execute(
                        select(Correction).where(Correction.student_id == user.id)
                    ).scalars().all()
                    for c in corrs:
                        export["corrections"].append({
                            "homework_key": c.homework_key,
                            "question_id": c.question_id,
                            "original_answer": c.original_answer,
                            "attempts": c.attempts,
                            "status": c.status,
                            "created_at": str(c.created_at) if c.created_at else None,
                        })

                    snaps = session.execute(
                        select(AnalyticsSnapshot).where(AnalyticsSnapshot.student_id == user.id)
                    ).scalars().all()
                    for s in snaps:
                        export["analytics"][s.snapshot_type] = s.data
            return export
        except Exception as e:
            logger.warning("PG export failed for %s: %s, falling back to JSON", student_id, e)

    # --- JSON fallback path ---
    from engine.grader import load_json

    # Profile from students.json
    students = load_json("students.json").get("students", [])
    student = next((s for s in students if s["id"] == student_id), None)
    if student:
        export["profile"] = student

    # Submissions from answers.json
    answers = load_json("answers.json")
    for key, record in answers.items():
        if record.get("student_id") == student_id:
            export["submissions"].append({
                "submission_key": key,
                "assignment_id": record.get("assignment_id", ""),
                "answers": record.get("answers", {}),
            })

    # Corrections from corrections.json
    corrections = load_json("corrections.json")
    for hw_key, hw_corrections in corrections.items():
        for sub_key, record in hw_corrections.items():
            if record.get("student_id") == student_id:
                export["corrections"].append({
                    "homework_key": hw_key.replace("_corrections", ""),
                    "question_id": record.get("question_id", ""),
                    "original_answer": record.get("original_answer", ""),
                    "attempts": record.get("attempts", []),
                    "status": record.get("status", "open"),
                })

    # Analytics from JSON files
    for fname, key in [
        ("growth_report.json", "growth_report"),
        ("student_dashboard.json", "student_dashboard"),
        ("knowledge_tree.json", "knowledge_tree"),
    ]:
        try:
            data = load_json(fname)
            if isinstance(data, dict) and student_id in data:
                export["analytics"][key] = data[student_id]
        except Exception:
            pass

    return export
