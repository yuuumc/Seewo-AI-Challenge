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
