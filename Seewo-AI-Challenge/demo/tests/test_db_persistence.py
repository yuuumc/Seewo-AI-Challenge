"""Tests for V1.0 DB persistence layer (orm / migration / db_store).

Uses SQLite for testing (no PG dependency required).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# Ensure demo/ and repo root are on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ── ORM model tests ──

class TestORMModels:
    """Verify all 8 ORM models can create tables and accept data."""

    def test_all_tables_created(self):
        from infra.pg.orm import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        table_names = sorted(Base.metadata.tables.keys())
        assert "users" in table_names
        assert "classes" in table_names
        assert "homeworks" in table_names
        assert "submissions" in table_names
        assert "grading_results" in table_names
        assert "corrections" in table_names
        assert "analytics_snapshots" in table_names
        assert "agent_trace" in table_names
        # V2.0 Sprint 5: 3 new organization tree tables
        assert "schools" in table_names
        assert "grades" in table_names
        assert "subject_groups" in table_names
        assert len(table_names) == 11

    def test_user_has_v1_fields(self):
        from infra.pg.orm import Base, User
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            u = User(
                username="test_user",
                email="test@test.com",
                password_hash="hash",
                role="student",
                display_name="测试",
                avatar_color="#FF0000",
                student_level="A",
            )
            s.add(u)
            s.commit()
            loaded = s.execute(select(User).where(User.username == "test_user")).scalar_one()
            assert loaded.avatar_color == "#FF0000"
            assert loaded.student_level == "A"

    def test_homework_submission_relationship(self):
        from infra.pg.orm import Base, User, Homework, Submission
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            u = User(username="s01", email="s01@t.com", password_hash="h", role="student")
            hw = Homework(hw_key="hw_001", title="Test", subject="数学",
                          knowledge_points=["a"], questions=[{"id": "q1"}])
            s.add_all([u, hw])
            s.commit()

            sub = Submission(
                student_id=u.id, homework_id=hw.id,
                submission_key="s01_hw_001", answers={"q1": "D"},
            )
            s.add(sub)
            s.commit()

            loaded = s.execute(select(Submission)).scalar_one()
            assert loaded.student.username == "s01"
            assert loaded.homework.hw_key == "hw_001"
            assert loaded.answers == {"q1": "D"}


# ── Migration script tests ──

class TestMigrationScript:
    """Verify the JSON → PG migration produces correct data."""

    @pytest.fixture(scope="class")
    def migrated_db(self, tmp_path_factory):
        """Run migration against a temp SQLite DB."""
        db_path = tmp_path_factory.mktemp("db") / "test.db"
        db_url = f"sqlite:///{db_path}"

        # Import and run migration
        from scripts.migrate_json_to_pg import main as migrate_main
        import argparse

        # We need to call main with args — use sys.argv patching
        orig_argv = sys.argv
        data_dir = str(_DEMO_DIR / "data")
        sys.argv = [
            "migrate_json_to_pg.py",
            "--db-url", db_url,
            "--data-dir", data_dir,
            "--create-tables",
        ]
        try:
            migrate_main()
        finally:
            sys.argv = orig_argv

        return db_url

    def test_users_migrated(self, migrated_db):
        from infra.pg.orm import User
        engine = create_engine(migrated_db)
        with Session(engine) as s:
            users = s.execute(select(User)).scalars().all()
            assert len(users) == 8
            usernames = {u.username for u in users}
            assert "teacher" in usernames
            assert "s01" in usernames
            assert "s05" in usernames

    def test_students_have_metadata(self, migrated_db):
        from infra.pg.orm import User
        engine = create_engine(migrated_db)
        with Session(engine) as s:
            s01 = s.execute(select(User).where(User.username == "s01")).scalar_one()
            assert s01.display_name == "林小川"
            assert s01.avatar_color == "#4A90D9"
            assert s01.student_level == "A"
            assert s01.role == "student"

    def test_homework_migrated(self, migrated_db):
        from infra.pg.orm import Homework
        engine = create_engine(migrated_db)
        with Session(engine) as s:
            hw = s.execute(select(Homework).where(Homework.hw_key == "hw_001")).scalar_one()
            assert "函数单调性" in hw.title
            assert len(hw.questions) == 6
            assert "导数的计算" in hw.knowledge_points

    def test_submissions_migrated(self, migrated_db):
        from infra.pg.orm import Submission, User
        engine = create_engine(migrated_db)
        with Session(engine) as s:
            subs = s.execute(select(Submission)).scalars().all()
            assert len(subs) == 5
            for sub in subs:
                assert len(sub.answers) == 6  # 6 questions per submission

    def test_corrections_migrated(self, migrated_db):
        from infra.pg.orm import Correction
        engine = create_engine(migrated_db)
        with Session(engine) as s:
            corrs = s.execute(select(Correction)).scalars().all()
            assert len(corrs) == 6
            for c in corrs:
                assert c.status == "closed"
                assert len(c.attempts) >= 1

    def test_analytics_migrated(self, migrated_db):
        from infra.pg.orm import AnalyticsSnapshot
        engine = create_engine(migrated_db)
        with Session(engine) as s:
            snaps = s.execute(select(AnalyticsSnapshot)).scalars().all()
            types = {snap.snapshot_type for snap in snaps}
            assert "growth_report" in types
            assert "student_dashboard" in types
            assert "knowledge_tree" in types

    def test_migration_is_idempotent(self, migrated_db):
        """Running migration twice should not duplicate rows."""
        from infra.pg.orm import User, Submission
        # Run again
        orig_argv = sys.argv
        data_dir = str(_DEMO_DIR / "data")
        sys.argv = [
            "migrate_json_to_pg.py",
            "--db-url", migrated_db,
            "--data-dir", data_dir,
        ]
        try:
            from scripts.migrate_json_to_pg import main as migrate_main
            migrate_main()
        finally:
            sys.argv = orig_argv

        engine = create_engine(migrated_db)
        with Session(engine) as s:
            users = s.execute(select(User)).scalars().all()
            subs = s.execute(select(Submission)).scalars().all()
            assert len(users) == 8  # still 8, not 16
            assert len(subs) == 5   # still 5, not 10


# ── db_store fallback tests ──

class TestDBStoreFallback:
    """When PG is unavailable, db_store should fall back to DEMO_USERS."""

    def test_fallback_to_demo_users(self):
        """Without PG, get_user should return DEMO_USERS data."""
        import db_store
        db_store.reset_pg_cache()

        # Force PG to be unavailable by pointing to a bad URL
        os.environ["DATABASE_URL_SYNC"] = "postgresql+psycopg2://nobody:nobody@127.0.0.1:1/nonexistent"
        db_store.reset_pg_cache()

        user = db_store.get_user("teacher")
        assert user is not None
        assert user["role"] == "teacher"
        assert user["name"] == "李老师"

        # Cleanup
        del os.environ["DATABASE_URL_SYNC"]
        db_store.reset_pg_cache()

    def test_sqlite_mode_works(self):
        """With SQLite URL, db_store should use the DB directly."""
        import db_store
        from infra.pg.orm import Base, User

        # Create a temp SQLite DB with a user
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as s:
            u = User(
                username="sqlite_user",
                email="sqlite@test.com",
                password_hash="$2b$12$dummyhash",
                role="teacher",
                display_name="SQLite老师",
            )
            s.add(u)
            s.commit()

        # Point db_store to this engine
        db_store._pg_engine = engine
        db_store._pg_available = True

        user = db_store.get_user("sqlite_user")
        assert user is not None
        assert user["name"] == "SQLite老师"
        assert user["role"] == "teacher"

        # Cleanup
        db_store.reset_pg_cache()
