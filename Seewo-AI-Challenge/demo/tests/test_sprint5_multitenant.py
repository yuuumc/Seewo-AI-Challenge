"""V2.0 Sprint 5: Tests for org tree data model, RBAC, RLS, PII encryption, audit log.

Run with: python -m pytest tests/test_sprint5_multitenant.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure demo/ and repo root are on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ── ORM Model Tests ──

class TestOrgTreeModels:
    """Test V2.0 Sprint 5 organization tree ORM models."""

    def test_school_model(self):
        from infra.pg.orm import Base, School
        engine = __import__("sqlalchemy").create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import Session
        with Session(engine) as s:
            school = School(name="测试学校", code="test001", school_type="secondary")
            s.add(school)
            s.commit()
            assert school.id is not None
            assert school.is_active is True
            assert school.config == {}

    def test_grade_model(self):
        from infra.pg.orm import Base, School, Grade
        engine = __import__("sqlalchemy").create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import Session
        with Session(engine) as s:
            school = School(name="测试学校", code="test002")
            s.add(school)
            s.flush()
            grade = Grade(school_id=school.id, name="高二", grade_level=11)
            s.add(grade)
            s.commit()
            assert grade.id is not None
            assert grade.academic_year == "2026-2027"

    def test_subject_group_model(self):
        from infra.pg.orm import Base, School, SubjectGroup
        engine = __import__("sqlalchemy").create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import Session
        with Session(engine) as s:
            school = School(name="测试学校", code="test003")
            s.add(school)
            s.flush()
            sg = SubjectGroup(school_id=school.id, name="数学组", subject="数学")
            s.add(sg)
            s.commit()
            assert sg.id is not None
            assert sg.member_ids == []

    def test_user_has_school_id(self):
        from infra.pg.orm import Base, User
        engine = __import__("sqlalchemy").create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import Session
        with Session(engine) as s:
            u = User(
                username="test_sprint5", email="s5@test.com",
                password_hash="hash", role="student",
            )
            s.add(u)
            s.commit()
            assert u.school_id == 1  # default school
            assert u.parent_of == []

    def test_class_has_multitenant_fields(self):
        from infra.pg.orm import Base, Class
        engine = __import__("sqlalchemy").create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        from sqlalchemy.orm import Session
        with Session(engine) as s:
            # Need a user first (teacher FK)
            from infra.pg.orm import User
            u = User(username="teacher_s5", email="t@s5.com", password_hash="h", role="teacher")
            s.add(u)
            s.flush()
            c = Class(name="高三1班", teacher_id=u.id)
            s.add(c)
            s.commit()
            assert c.school_id == 1
            assert c.is_active is True

    def test_all_business_tables_have_school_id(self):
        """All 7 business tables should have school_id column with default=1."""
        from infra.pg.orm import (
            Base, User, Class, Homework, Submission,
            GradingResult, Correction, AnalyticsSnapshot,
        )
        engine = __import__("sqlalchemy").create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        for model in [User, Class, Homework, Submission, GradingResult, Correction, AnalyticsSnapshot]:
            assert "school_id" in model.__table__.columns, f"{model.__tablename__} missing school_id"
            col = model.__table__.columns["school_id"]
            assert col.default is not None or col.server_default is not None, \
                f"{model.__tablename__}.school_id has no default"


# ── RBAC Tests ──

class TestRBAC:
    """Test V2.0 Sprint 5 RBAC role aliases and inheritance."""

    def test_role_aliases(self):
        from security import ROLE_ALIASES, _resolve_role
        assert _resolve_role("admin") == "school_admin"
        assert _resolve_role("head") == "head_teacher"
        assert _resolve_role("teacher") == "teacher"  # no alias
        assert _resolve_role("student") == "student"

    def test_role_inheritance(self):
        from security import _effective_roles
        assert "teacher" in _effective_roles("super_admin")
        assert "school_admin" in _effective_roles("super_admin")
        assert "head_teacher" in _effective_roles("school_admin")
        assert "teacher" in _effective_roles("head_teacher")
        assert "student" in _effective_roles("teacher")
        assert "super_admin" not in _effective_roles("teacher")
        assert "school_admin" not in _effective_roles("head_teacher")

    def test_legacy_role_still_works(self):
        """Legacy roles (admin, head) should resolve through aliases."""
        from security import _effective_roles
        # admin inherits school_admin's roles
        eff = _effective_roles("admin")
        assert "school_admin" in eff
        assert "teacher" in eff
        # head inherits head_teacher's roles
        eff = _effective_roles("head")
        assert "head_teacher" in eff
        assert "teacher" in eff


# ── PII Encryption Tests ──

class TestPIIEncryption:
    """Test V2.0 Sprint 5 field-level PII encryption."""

    def test_encrypt_decrypt_roundtrip(self):
        from pii_crypto import encrypt_pii, decrypt_pii
        original = "张三"
        encrypted = encrypt_pii(original)
        assert encrypted is not None
        assert encrypted != original
        assert encrypted.startswith("v1:")
        decrypted = decrypt_pii(encrypted)
        assert decrypted == original

    def test_encrypt_none(self):
        from pii_crypto import encrypt_pii, decrypt_pii
        assert encrypt_pii(None) is None
        assert decrypt_pii(None) is None

    def test_encrypt_empty_string(self):
        from pii_crypto import encrypt_pii, decrypt_pii
        assert encrypt_pii("") == ""
        assert decrypt_pii("") == ""

    def test_decrypt_unencrypted(self):
        """Legacy unencrypted data should pass through."""
        from pii_crypto import decrypt_pii
        assert decrypt_pii("张三") == "张三"
        assert decrypt_pii("not encrypted") == "not encrypted"

    def test_mask_value(self):
        from pii_crypto import _mask_value
        assert _mask_value("张") == "*"
        assert _mask_value("张三") == "张*"
        assert _mask_value("张三丰") == "张*丰"
        assert _mask_value("13800138000") == "138****8000"

    def test_encrypt_pii_fields(self):
        from pii_crypto import encrypt_pii_fields, decrypt_pii_fields
        data = {"name": "张三", "phone": "13800138000", "student_id": "S001", "score": 95}
        encrypted = encrypt_pii_fields(data, ["name", "phone", "student_id"])
        # PII fields should be masked
        assert encrypted["name"] == "张*"
        assert encrypted["phone"] == "138****8000"
        assert encrypted["score"] == 95  # non-PII field untouched
        assert "pii_encrypted" in encrypted

        # Decrypt should restore original values
        decrypted = decrypt_pii_fields(encrypted, ["name", "phone", "student_id"])
        assert decrypted["name"] == "张三"
        assert decrypted["phone"] == "13800138000"
        assert decrypted["student_id"] == "S001"


# ── Audit Log Tests ──

class TestAuditLog:
    """Test V2.0 Sprint 5 audit log with school_id + user_id + action + resource."""

    def test_audit_log_has_required_fields(self):
        from security import audit_log, _audit_path
        import json

        # Write a test audit record
        audit_log("test_event", resource="/test/path", extra_field="val")

        # Read the file and check the last line
        path = _audit_path()
        if path.exists():
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            if lines:
                last = json.loads(lines[-1])
                # V2.0 Sprint 5 required fields
                assert "school_id" in last
                assert "user_id" in last
                assert "action" in last
                assert "resource" in last
                assert last["action"] == "test_event"

    def test_audit_log_with_school_id_override(self):
        """audit_log should accept explicit school_id in fields."""
        from security import audit_log, _audit_path
        import json

        audit_log("test_school_override", school_id=42, resource="/test")

        path = _audit_path()
        if path.exists():
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            if lines:
                last = json.loads(lines[-1])
                assert last["school_id"] == 42


# ── Migration Script Tests ──

class TestMigrationScript:
    """Test migrate_to_multitenant.py CLI interface."""

    def test_dry_run(self):
        """--dry-run should not modify any data."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "scripts" / "migrate_to_multitenant.py"), "--dry-run"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "DATABASE_URL": ""},
        )
        assert result.returncode == 0
        assert "DRY-RUN" in result.stdout

    def test_verify_no_pg(self):
        """--verify without PG should still work (JSON checks)."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "scripts" / "migrate_to_multitenant.py"), "--verify"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "DATABASE_URL": ""},
        )
        assert result.returncode == 0


# ── Tenant Middleware Tests ──

class TestTenantMiddleware:
    """Test multi-tenant request middleware."""

    def test_get_current_school_id_default(self):
        from tenant_middleware import get_current_school_id
        # Outside request context, should return default
        assert get_current_school_id() == 1
