#!/usr/bin/env python3
"""JSON → PostgreSQL migration script (V1.0 Sprint 1).

Reads the 10 JSON files in demo/data/ and populates the PG tables:
  - students.json + DEMO_USERS → users
  - questions.json → homeworks
  - answers.json → submissions
  - corrections.json → corrections
  - growth_report.json / student_dashboard.json / knowledge_tree.json → analytics_snapshots

Usage:
  python scripts/migrate_json_to_pg.py [--db-url postgresql+psycopg2://...] [--data-dir demo/data]

Defaults:
  --db-url: from env DATABASE_URL_SYNC or postgresql+psycopg2://seewo:sewo@localhost:5432/seewo
  --data-dir: demo/data (relative to repo root)

The script is idempotent: running it twice won't create duplicate rows
(unique constraints + upsert logic).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add repo root to sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import bcrypt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from infra.pg.orm import (
    AnalyticsSnapshot,
    Base,
    Correction,
    GradingResult,
    Homework,
    Submission,
    User,
)


# ── Demo user seed (aligned with demo/security.py DEMO_USERS) ──
_DEMO_USER_SEED = {
    "teacher": {"name": "李老师", "role": "teacher", "password": "teacher123", "email": "teacher@seewo.edu"},
    "head": {"name": "王组长", "role": "head", "password": "head123", "email": "head@seewo.edu"},
    "admin": {"name": "张主任", "role": "admin", "password": "admin123", "email": "admin@seewo.edu"},
    "s01": {"name": "林小川", "role": "student", "password": "student123", "email": "s01@seewo.edu",
            "class": "高二(3)班", "level": "A", "avatar_color": "#4A90D9"},
    "s02": {"name": "陈雨桐", "role": "student", "password": "student123", "email": "s02@seewo.edu",
            "class": "高二(3)班", "level": "B", "avatar_color": "#7B68EE"},
    "s03": {"name": "王浩然", "role": "student", "password": "student123", "email": "s03@seewo.edu",
            "class": "高二(3)班", "level": "C", "avatar_color": "#E67E22"},
    "s04": {"name": "赵思远", "role": "student", "password": "student123", "email": "s04@seewo.edu",
            "class": "高二(3)班", "level": "A", "avatar_color": "#2ECC71"},
    "s05": {"name": "刘雨涵", "role": "student", "password": "student123", "email": "s05@seewo.edu",
            "class": "高二(3)班", "level": "B", "avatar_color": "#E74C3C"},
}


def load_json(data_dir: Path, name: str):
    with open(data_dir / name, "r", encoding="utf-8") as f:
        return json.load(f)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def migrate_users(session: Session, students_data: dict) -> dict[str, int]:
    """Migrate DEMO_USERS + students.json → users table. Returns username→id mapping."""
    students_list = students_data.get("students", [])
    student_meta = {s["id"]: s for s in students_list}

    username_to_id = {}
    for username, seed in _DEMO_USER_SEED.items():
        existing = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()

        password_hash = hash_password(seed["password"])
        meta = student_meta.get(username, {})

        if existing:
            # Update existing user
            existing.display_name = seed["name"]
            existing.role = seed["role"]
            existing.email = seed["email"]
            existing.password_hash = password_hash
            existing.avatar_color = meta.get("avatar_color") or seed.get("avatar_color")
            existing.student_level = meta.get("level") or seed.get("level")
            session.flush()
            username_to_id[username] = existing.id
        else:
            user = User(
                username=username,
                email=seed["email"],
                password_hash=password_hash,
                role=seed["role"],
                display_name=seed["name"],
                avatar_color=meta.get("avatar_color") or seed.get("avatar_color"),
                student_level=meta.get("level") or seed.get("level"),
            )
            session.add(user)
            session.flush()
            username_to_id[username] = user.id

    session.commit()
    print(f"  users: {len(username_to_id)} rows (upserted)")
    return username_to_id


def migrate_homeworks(session: Session, questions_data: dict) -> dict[str, int]:
    """Migrate questions.json → homeworks table. Returns hw_key→id mapping."""
    hw_key_to_id = {}
    for hw_key, hw_data in questions_data.items():
        existing = session.execute(
            select(Homework).where(Homework.hw_key == hw_key)
        ).scalar_one_or_none()

        if existing:
            existing.title = hw_data.get("title", "")
            existing.subject = hw_data.get("subject", "数学")
            existing.grade = hw_data.get("grade")
            existing.knowledge_points = hw_data.get("knowledge_points", [])
            existing.questions = hw_data.get("questions", [])
            session.flush()
            hw_key_to_id[hw_key] = existing.id
        else:
            hw = Homework(
                hw_key=hw_key,
                title=hw_data.get("title", ""),
                subject=hw_data.get("subject", "数学"),
                grade=hw_data.get("grade"),
                knowledge_points=hw_data.get("knowledge_points", []),
                questions=hw_data.get("questions", []),
            )
            session.add(hw)
            session.flush()
            hw_key_to_id[hw_key] = hw.id

    session.commit()
    print(f"  homeworks: {len(hw_key_to_id)} rows (upserted)")
    return hw_key_to_id


def migrate_submissions(session: Session, answers_data: dict, username_to_id: dict, hw_key_to_id: dict) -> int:
    """Migrate answers.json → submissions table."""
    count = 0
    for submission_key, sub_data in answers_data.items():
        student_username = sub_data.get("student_id", "")
        hw_key = sub_data.get("assignment_id", "")

        student_id = username_to_id.get(student_username)
        homework_id = hw_key_to_id.get(hw_key)
        if not student_id or not homework_id:
            print(f"  WARN: skip {submission_key} — student_id={student_id}, homework_id={homework_id}")
            continue

        existing = session.execute(
            select(Submission).where(Submission.submission_key == submission_key)
        ).scalar_one_or_none()

        if existing:
            existing.student_id = student_id
            existing.homework_id = homework_id
            existing.answers = sub_data.get("answers", {})
            session.flush()
        else:
            sub = Submission(
                student_id=student_id,
                homework_id=homework_id,
                submission_key=submission_key,
                answers=sub_data.get("answers", {}),
            )
            session.add(sub)
            session.flush()
        count += 1

    session.commit()
    print(f"  submissions: {count} rows (upserted)")
    return count


def migrate_corrections(session: Session, corrections_data: dict, username_to_id: dict) -> int:
    """Migrate corrections.json → corrections table."""
    count = 0
    for hw_key, hw_corrections in corrections_data.items():
        # hw_key is like "hw_001_corrections"
        clean_hw_key = hw_key.replace("_corrections", "")
        for corr_key, corr_data in hw_corrections.items():
            # corr_key is like "s02_q5"
            student_username = corr_data.get("student_id", "")
            student_id = username_to_id.get(student_username)
            if not student_id:
                print(f"  WARN: skip correction {corr_key} — student not found")
                continue

            question_id = corr_data.get("question_id", "")

            # Check existing by student_id + homework_key + question_id
            existing = session.execute(
                select(Correction).where(
                    Correction.student_id == student_id,
                    Correction.homework_key == clean_hw_key,
                    Correction.question_id == question_id,
                )
            ).scalar_one_or_none()

            attempts = corr_data.get("attempts", [])
            status = corr_data.get("status", "open")
            original = corr_data.get("original_answer", "")

            if existing:
                existing.original_answer = original
                existing.attempts = attempts
                existing.status = status
                existing.updated_at = datetime.utcnow()
                session.flush()
            else:
                corr = Correction(
                    student_id=student_id,
                    homework_key=clean_hw_key,
                    question_id=question_id,
                    original_answer=original,
                    attempts=attempts,
                    status=status,
                )
                session.add(corr)
                session.flush()
            count += 1

    session.commit()
    print(f"  corrections: {count} rows (upserted)")
    return count


def migrate_analytics(session: Session, data_dir: Path, username_to_id: dict) -> int:
    """Migrate growth_report / student_dashboard / knowledge_tree → analytics_snapshots."""
    count = 0

    # growth_report.json — keyed by student_id
    growth_data = load_json(data_dir, "growth_report.json")
    for student_username, report in growth_data.items():
        student_id = username_to_id.get(student_username)
        if not student_id:
            continue
        _upsert_snapshot(session, student_id, "growth_report", report)
        count += 1

    # student_dashboard.json — keyed by student_id
    dashboard_data = load_json(data_dir, "student_dashboard.json")
    for student_username, dashboard in dashboard_data.items():
        student_id = username_to_id.get(student_username)
        if not student_id:
            continue
        _upsert_snapshot(session, student_id, "student_dashboard", dashboard)
        count += 1

    # knowledge_tree.json — shared tree, assign to all students
    tree_data = load_json(data_dir, "knowledge_tree.json")
    for student_username, student_id in username_to_id.items():
        if _DEMO_USER_SEED.get(student_username, {}).get("role") == "student":
            _upsert_snapshot(session, student_id, "knowledge_tree", tree_data)
            count += 1

    session.commit()
    print(f"  analytics_snapshots: {count} rows (upserted)")
    return count


def _upsert_snapshot(session: Session, student_id: int, snapshot_type: str, data: dict) -> None:
    """Insert or update an analytics snapshot (student_id + snapshot_type as natural key)."""
    existing = session.execute(
        select(AnalyticsSnapshot).where(
            AnalyticsSnapshot.student_id == student_id,
            AnalyticsSnapshot.snapshot_type == snapshot_type,
        )
    ).scalar_one_or_none()

    if existing:
        existing.data = data
        session.flush()
    else:
        snap = AnalyticsSnapshot(
            student_id=student_id,
            snapshot_type=snapshot_type,
            data=data,
        )
        session.add(snap)
        session.flush()


def main():
    parser = argparse.ArgumentParser(description="Migrate JSON data to PostgreSQL")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL_SYNC", "postgresql+psycopg2://seewo:seewo@localhost:5432/seewo"),
        help="SQLAlchemy sync DSN (default: from DATABASE_URL_SYNC env or localhost)",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_REPO_ROOT / "demo" / "data"),
        help="Path to demo/data directory",
    )
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Run Base.metadata.create_all() before migration (for dev/testing)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    print(f"JSON → PG Migration")
    print(f"  DB: {args.db_url}")
    print(f"  Data dir: {data_dir}")
    print()

    engine = create_engine(args.db_url)

    if args.create_tables:
        print("Creating tables (Base.metadata.create_all)...")
        Base.metadata.create_all(engine)
        print("  Tables created.\n")

    with Session(engine) as session:
        print("Migrating users...")
        students_data = load_json(data_dir, "students.json")
        username_to_id = migrate_users(session, students_data)

        print("Migrating homeworks...")
        questions_data = load_json(data_dir, "questions.json")
        hw_key_to_id = migrate_homeworks(session, questions_data)

        print("Migrating submissions...")
        answers_data = load_json(data_dir, "answers.json")
        migrate_submissions(session, answers_data, username_to_id, hw_key_to_id)

        print("Migrating corrections...")
        corrections_data = load_json(data_dir, "corrections.json")
        migrate_corrections(session, corrections_data, username_to_id)

        print("Migrating analytics snapshots...")
        migrate_analytics(session, data_dir, username_to_id)

    print("\nMigration complete!")


if __name__ == "__main__":
    main()
