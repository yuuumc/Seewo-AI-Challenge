"""V2.0 Sprint 7: Tests for MFA, permission tightening, and security audit.

Run with: python -m pytest tests/test_sprint7_security.py -v
"""
from __future__ import annotations

import os
import sys
import time
import ast
from pathlib import Path

import pytest

# Ensure demo/ and repo root are on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ── 7.1 MFA Tests ──

class TestMFA:
    """Test MFA TOTP generation, verification, and login flow."""

    def test_generate_totp_secret(self):
        from mfa import generate_totp_secret
        secret = generate_totp_secret()
        assert len(secret) >= 16
        # Base32 encoding
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)

    def test_verify_totp_valid(self):
        import pyotp
        from mfa import verify_totp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp(secret, code) is True

    def test_verify_totp_invalid(self):
        from mfa import verify_totp
        secret = "JBSWY3DPEHPK3PXP"
        assert verify_totp(secret, "000000") is False
        assert verify_totp(secret, "") is False
        assert verify_totp(secret, "abcdef") is False
        assert verify_totp(secret, "12345") is False

    def test_provisioning_uri(self):
        from mfa import get_provisioning_uri
        secret = "JBSWY3DPEHPK3PXP"
        uri = get_provisioning_uri(secret, "testuser")
        assert uri.startswith("otpauth://totp/")
        assert "Seewo-AI-Challenge" in uri
        assert "testuser" in uri

    def test_mfa_demo_mode_skipped(self):
        """Demo mode (DEMO_AUTH_OPEN=1) should skip MFA."""
        os.environ["DEMO_AUTH_OPEN"] = "1"
        from mfa import mfa_check_after_login
        required, redirect = mfa_check_after_login("admin", {"role": "admin"})
        assert required is False
        assert redirect is None
        # Cleanup
        os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_mfa_not_enabled_by_default(self):
        """Users without MFA setup should not require MFA."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        from mfa import mfa_check_after_login
        required, redirect = mfa_check_after_login("admin", {"role": "admin"})
        assert required is False
        assert redirect is None
        os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_mfa_enabled_triggers_pending(self):
        """When MFA is enabled, login should trigger pending state."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        from security import DEMO_USERS
        # Temporarily enable MFA for admin
        DEMO_USERS["admin"]["mfa_enabled"] = True
        DEMO_USERS["admin"]["mfa_secret"] = "JBSWY3DPEHPK3PXP"

        from flask import Flask
        app = Flask(__name__, template_folder=str(Path(_DEMO_DIR) / "templates"))
        app.config["SECRET_KEY"] = "test"
        from mfa import register_mfa_routes
        register_mfa_routes(app)
        with app.test_request_context():
            from mfa import mfa_check_after_login
            required, redirect = mfa_check_after_login("admin", {"role": "admin"})
            assert required is True

        # Cleanup
        DEMO_USERS["admin"]["mfa_enabled"] = False
        DEMO_USERS["admin"]["mfa_secret"] = None
        os.environ["DEMO_AUTH_OPEN"] = "1"


# ── 7.2 Permission Tightening Tests ──

class TestPermissionTightening:
    """Test that permission tightening is applied correctly."""

    def test_min_role_decorator_exists(self):
        from security import min_role, ROLE_LEVELS
        assert "student" in ROLE_LEVELS
        assert "teacher" in ROLE_LEVELS
        assert "admin" in ROLE_LEVELS
        assert ROLE_LEVELS["student"] < ROLE_LEVELS["teacher"]
        assert ROLE_LEVELS["teacher"] < ROLE_LEVELS["admin"]

    def test_min_role_allows_higher(self):
        from security import min_role, _resolve_role, ROLE_LEVELS
        # admin should pass min_role("teacher")
        admin_level = ROLE_LEVELS[_resolve_role("admin")]
        teacher_level = ROLE_LEVELS[_resolve_role("teacher")]
        assert admin_level >= teacher_level

    def test_class_delete_no_teacher(self):
        """class_delete should NOT allow teacher role (tightened in 7.2)."""
        import ast
        batch_path = Path(_DEMO_DIR) / "org_api.py"
        source = batch_path.read_text()
        # Find the class_delete function and check its roles_required
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "class_delete":
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and hasattr(dec.func, 'id') and dec.func.id == 'roles_required':
                        roles = [arg.value for arg in dec.args if isinstance(arg, ast.Constant)]
                        assert "teacher" not in roles, "class_delete should not allow teacher"
                        assert "admin" in roles
                        assert "head" in roles
                        return
        pytest.fail("class_delete function not found")

    def test_import_endpoints_no_teacher(self):
        """Import endpoints should NOT allow teacher role (tightened in 7.2)."""
        source = (Path(_DEMO_DIR) / "batch_import.py").read_text()
        tree = ast.parse(source)
        import_funcs = [n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and "import" in n.name]
        assert len(import_funcs) >= 3
        for func in import_funcs:
            for dec in func.decorator_list:
                if isinstance(dec, ast.Call) and hasattr(dec.func, 'id') and dec.func.id == 'roles_required':
                    roles = [arg.value for arg in dec.args if isinstance(arg, ast.Constant)]
                    assert "teacher" not in roles, f"{func.name} should not allow teacher"

    def test_delete_student_data_admin_only(self):
        """api_delete_student_data should only allow admin."""
        source = (Path(_DEMO_DIR) / "app.py").read_text()
        # Check that the delete endpoint has @roles_required("admin")
        assert '@roles_required("admin")' in source

    def test_export_student_data_restricted(self):
        """api_export_student_data should not allow teachers (student own-data OK via IDOR)."""
        source = (Path(_DEMO_DIR) / "app.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "api_export_student_data":
                func_body = ast.get_source_segment(source, node)
                assert func_body is not None
                assert "student" in func_body, "export should handle student IDOR"
                assert "admin" in func_body, "export should allow admin"
                assert "forbidden" in func_body, "export should block unauthorized roles"
                return
        pytest.fail("api_export_student_data not found")


# ── 7.3 Security Audit Tests ──

class TestSecurityAudit:
    """Test that bandit High/Critical findings are fixed."""

    def test_no_jinja_autoescape_false_in_tests(self):
        """No Jinja2 Environment should be created without autoescape=True."""
        import ast
        test_dir = Path(_DEMO_DIR) / "tests"
        for py_file in test_dir.glob("*.py"):
            source = py_file.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and hasattr(node.func, 'id') and node.func.id == 'Environment':
                    # Check if autoescape=True is in kwargs
                    has_autoescape = False
                    for kw in node.keywords:
                        if kw.arg == 'autoescape':
                            has_autoescape = True
                            if isinstance(kw.value, ast.Constant):
                                assert kw.value.value is True, \
                                    f"{py_file.name}: autoescape must be True"
                    # Environment() without autoescape is flagged by bandit
                    # but only if it's used with HTML templates
                    if not has_autoescape:
                        # This is a B701 finding — flag it
                        pytest.fail(
                            f"{py_file.name}:{node.lineno}: Environment() without autoescape=True"
                        )

    def test_no_hardcoded_secrets(self):
        """Check for obvious hardcoded secrets in source code."""
        import re
        dangerous_patterns = [
            r'password\s*=\s*["\'][^"\']{8,}["\']',  # password = "something"
            r'secret_key\s*=\s*["\'][^"\']{8,}["\']',  # secret_key = "something"
            r'api_key\s*=\s*["\'][^"\']{20,}["\']',  # api_key = "something_long"
        ]
        src_dir = Path(_DEMO_DIR)
        for py_file in src_dir.rglob("*.py"):
            if "tests/" in str(py_file) or "test_" in py_file.name:
                continue
            source = py_file.read_text()
            for pattern in dangerous_patterns:
                matches = re.findall(pattern, source, re.IGNORECASE)
                # Filter out known safe patterns
                matches = [m for m in matches if "change-me" not in m.lower()
                          and "demo-secret" not in m.lower()
                          and "test" not in m.lower()
                          and "example" not in m.lower()
                          and "placeholder" not in m.lower()]
                assert not matches, f"{py_file.name}: hardcoded secret: {matches}"

    def test_audit_report_exists(self):
        """Security audit report should be generated."""
        report_path = Path(_DEMO_DIR) / "SECURITY_AUDIT_REPORT.md"
        assert report_path.exists(), "Security audit report not found"
        content = report_path.read_text()
        assert "bandit" in content.lower()
        assert "High" in content or "HIGH" in content
        assert "Medium" in content or "MEDIUM" in content
        assert "修复" in content or "fixed" in content.lower()

    def test_no_sql_injection_raw_strings(self):
        """Check for raw SQL string formatting (potential injection)."""
        import re
        src_dir = Path(_DEMO_DIR)
        for py_file in src_dir.rglob("*.py"):
            if "tests/" in str(py_file) or "test_" in py_file.name:
                continue
            source = py_file.read_text()
            # Check for f-string or .format() in SQL execution
            dangerous_sql = re.findall(
                r'(execute|executemany)\s*\(\s*f["\']', source
            )
            assert not dangerous_sql, \
                f"{py_file.name}: potential SQL injection via f-string in execute()"


# ── Flask Integration: MFA routes ──

class TestMFAFlaskIntegration:
    """Test MFA routes work with Flask app."""

    def _make_test_app(self):
        """Create a minimal Flask app with MFA routes + login route + templates."""
        from flask import Flask, render_template_string
        app = Flask(
            __name__,
            template_folder=str(Path(_DEMO_DIR) / "templates"),
        )
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test"

        from security import register_template_helpers, register_error_handlers
        register_template_helpers(app)
        register_error_handlers(app)

        # Minimal login route for url_for to work
        @app.route("/login")
        def login():
            return "login"

        @app.route("/")
        def index():
            return "index"

        @app.route("/logout", methods=["POST"])
        def logout():
            return "logout"

        from mfa import register_mfa_routes
        register_mfa_routes(app)
        return app

    def test_mfa_verify_redirects_when_not_pending(self):
        """GET /mfa-verify without pending state should redirect to login."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        app = self._make_test_app()

        with app.test_client() as c:
            resp = c.get("/mfa-verify")
            assert resp.status_code == 302
            assert "/login" in resp.headers.get("Location", "")
        os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_mfa_setup_demo_mode(self):
        """GET /admin/mfa-setup in demo mode should show demo message."""
        os.environ["DEMO_AUTH_OPEN"] = "1"
        app = self._make_test_app()

        with app.test_client() as c:
            resp = c.get("/admin/mfa-setup")
            assert resp.status_code == 200
            # Should contain demo mode text
            assert b"\xe6\xbc\x94\xe7\xa4\xba" in resp.data or b"demo" in resp.data.lower()
        os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_mfa_verify_page_renders(self):
        """GET /mfa-verify with pending state should show verify page."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        app = self._make_test_app()

        with app.test_client() as c:
            # Set up pending MFA state
            with c.session_transaction() as sess:
                from mfa import MFA_SESSION_KEY
                sess[MFA_SESSION_KEY] = {
                    "username": "testuser",
                    "role": "admin",
                    "name": "Test",
                    "school_id": 1,
                    "timestamp": time.time(),
                }

            # GET should show verify page
            resp = c.get("/mfa-verify")
            assert resp.status_code == 200

        os.environ["DEMO_AUTH_OPEN"] = "1"
