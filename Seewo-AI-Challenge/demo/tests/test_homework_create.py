"""Tests for V1.0 Sprint 2: homework creation + multi-homework dashboard.

Tests cover:
  - GET /teacher/homework/create renders the form (demo + prod mode)
  - POST /teacher/homework/create creates homework in JSON fallback
  - GET /teacher shows multi-homework list with create button
  - _list_all_homeworks() returns homeworks from JSON fallback
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from _helpers import get_csrf_token, login
from engine.grader import load_json


def _ensure_login(client):
    """Log in as teacher if in prod mode (DEMO_AUTH_OPEN=0)."""
    if os.environ.get("DEMO_AUTH_OPEN", "0") == "0":
        login(client, "teacher", "teacher123")


def _get_csrf(client):
    """Get CSRF token for POST requests in prod mode."""
    _ensure_login(client)
    return get_csrf_token(client)


class TestHomeworkCreation:
    """Test the homework creation flow."""

    def test_create_form_renders(self, client):
        """GET /teacher/homework/create should render the form."""
        _ensure_login(client)
        resp = client.get("/teacher/homework/create")
        assert resp.status_code == 200
        assert "创建作业".encode() in resp.data
        assert "题目列表".encode() in resp.data

    def test_create_form_has_csrf(self, client):
        """Form should include CSRF token field."""
        _ensure_login(client)
        resp = client.get("/teacher/homework/create")
        assert b"csrf_token" in resp.data

    def test_create_homework_json_fallback(self, client):
        """POST /teacher/homework/create should save to JSON in demo mode."""
        _ensure_login(client)
        token = get_csrf_token(client)
        questions_payload = json.dumps([
            {"id": "q1", "type": "choice", "stem": "1+1=?", "score": 5,
             "knowledge": "算术", "answer": "B"},
        ])
        resp = client.post("/teacher/homework/create", data={
            "title": "测试作业_Sprint2",
            "subject": "数学",
            "grade": "高一",
            "knowledge_points": "算术, 加法",
            "target_class": "高一(1)班",
            "deadline": "2026-08-15T22:00",
            "questions_json": questions_payload,
            "csrf_token": token,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["hw_key"].startswith("hw_")
        assert "测试作业_Sprint2" in data["message"]

    def test_create_homework_missing_title(self, client):
        """POST without title should return 400."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/teacher/homework/create", data={
            "title": "",
            "questions_json": "[]",
            "csrf_token": token,
        })
        assert resp.status_code == 400

    def test_create_homework_no_questions(self, client):
        """POST without questions should return 400."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/teacher/homework/create", data={
            "title": "空作业",
            "questions_json": "[]",
            "csrf_token": token,
        })
        assert resp.status_code == 400

    def test_create_homework_bad_json(self, client):
        """POST with malformed questions_json should return 400."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/teacher/homework/create", data={
            "title": "坏数据作业",
            "questions_json": "not json{",
            "csrf_token": token,
        })
        assert resp.status_code == 400


class TestMultiHomeworkDashboard:
    """Test the multi-homework dashboard."""

    def test_dashboard_shows_homeworks(self, client):
        """GET /teacher should show homework list."""
        _ensure_login(client)
        resp = client.get("/teacher")
        assert resp.status_code == 200
        assert "函数单调性".encode() in resp.data

    def test_dashboard_has_create_button(self, client):
        """Dashboard should have '创建作业' button."""
        _ensure_login(client)
        resp = client.get("/teacher")
        assert "创建作业".encode() in resp.data

    def test_dashboard_shows_student_count(self, client):
        """Dashboard should show student count."""
        _ensure_login(client)
        resp = client.get("/teacher")
        assert "5".encode() in resp.data

    def test_dashboard_prod_mode_with_login(self, app):
        """Dashboard should work in prod mode with auth."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            client = app.test_client()
            login(client, "teacher", "teacher123")
            resp = client.get("/teacher")
            assert resp.status_code == 200
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"


class TestListAllHomeworks:
    """Test _list_all_homeworks() helper."""

    def test_returns_homeworks_from_json(self):
        """_list_all_homeworks() should return homeworks from JSON fallback."""
        from app import _list_all_homeworks
        homeworks = _list_all_homeworks()
        assert len(homeworks) >= 1
        hw = homeworks[0]
        assert "hw_key" in hw
        assert "title" in hw
        assert "questions" in hw
        assert "question_count" in hw
        assert "total_score" in hw

    def test_homework_structure(self):
        """Each homework should have all required fields."""
        from app import _list_all_homeworks
        homeworks = _list_all_homeworks()
        for hw in homeworks:
            assert isinstance(hw["hw_key"], str)
            assert isinstance(hw["title"], str)
            assert isinstance(hw["questions"], list)
            assert isinstance(hw["question_count"], int)
            assert isinstance(hw["total_score"], (int, float))

    def test_hw_001_exists(self):
        """The original hw_001 should be in the list."""
        from app import _list_all_homeworks
        homeworks = _list_all_homeworks()
        hw_keys = [hw["hw_key"] for hw in homeworks]
        assert "hw_001" in hw_keys


class TestSubjectType:
    """Test subject_type field in homework creation (Sprint 2 follow-up).

    Sprint 4 fix: these tests write via POST (which saves to PG when
    available) but then read via ``load_json("questions.json")`` (JSON
    fallback). When PG is running this mismatch causes assertion
    failures. The fix forces JSON fallback for these tests by
    monkeypatching ``db_store.is_pg_available`` to return False,
    ensuring the POST handler writes to JSON — matching the read path.
    """

    @pytest.fixture(autouse=True)
    def _force_json_storage(self, monkeypatch):
        """Force JSON fallback so write and read paths match."""
        import db_store
        monkeypatch.setattr(db_store, "is_pg_available", lambda: False)
        # Also patch the app-level import if it was already imported
        try:
            import app as _app_mod
            if hasattr(_app_mod, "is_pg_available"):
                monkeypatch.setattr(_app_mod, "is_pg_available", lambda: False)
        except ImportError:
            pass

    def test_create_homework_with_subject_type(self, client):
        """POST with subject_type in questions should persist it."""
        _ensure_login(client)
        token = get_csrf_token(client)
        questions_payload = json.dumps([
            {"id": "q1", "type": "long_answer", "subject_type": "physics_short",
             "stem": "一质量为 2kg 的物体在水平面上受 10N 拉力做匀加速运动，求加速度。",
             "score": 10, "knowledge": "牛顿第二定律", "answer": "a=5 m/s²"},
        ])
        resp = client.post("/teacher/homework/create", data={
            "title": "物理测试_学科类型",
            "subject": "物理",
            "grade": "高二",
            "knowledge_points": "牛顿第二定律",
            "target_class": "高二(1)班",
            "deadline": "2026-08-15T22:00",
            "questions_json": questions_payload,
            "csrf_token": token,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        hw_key = data["hw_key"]

        # Verify the saved homework has subject_type in question dict
        all_hw = load_json("questions.json")
        assert hw_key in all_hw
        saved_q = all_hw[hw_key]["questions"][0]
        assert saved_q["subject_type"] == "physics_short"

    def test_create_homework_defaults_subject_type(self, client):
        """Questions without subject_type should default to math_calculation."""
        _ensure_login(client)
        token = get_csrf_token(client)
        questions_payload = json.dumps([
            {"id": "q1", "type": "choice", "stem": "1+1=?", "score": 5,
             "knowledge": "算术", "answer": "B"},
        ])
        resp = client.post("/teacher/homework/create", data={
            "title": "默认学科类型测试",
            "subject": "数学",
            "grade": "高一",
            "knowledge_points": "算术",
            "target_class": "高一(1)班",
            "deadline": "",
            "questions_json": questions_payload,
            "csrf_token": token,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        hw_key = data["hw_key"]

        all_hw = load_json("questions.json")
        saved_q = all_hw[hw_key]["questions"][0]
        assert saved_q["subject_type"] == "math_calculation"

    def test_create_homework_mixed_subject_types(self, client):
        """Multiple questions with different subject_types should all persist."""
        _ensure_login(client)
        token = get_csrf_token(client)
        questions_payload = json.dumps([
            {"id": "q1", "type": "long_answer", "subject_type": "chinese_essay",
             "stem": "以《秋日》为题写一篇 800 字作文", "score": 40,
             "knowledge": "写作", "answer": ""},
            {"id": "q2", "type": "long_answer", "subject_type": "chemistry_short",
             "stem": "写出氢气在氧气中燃烧的化学方程式", "score": 10,
             "knowledge": "化学反应", "answer": "2H₂+O₂→2H₂O"},
        ])
        resp = client.post("/teacher/homework/create", data={
            "title": "混合学科测试",
            "subject": "综合",
            "grade": "高二",
            "knowledge_points": "写作, 化学反应",
            "target_class": "高二(1)班",
            "deadline": "",
            "questions_json": questions_payload,
            "csrf_token": token,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        hw_key = data["hw_key"]

        all_hw = load_json("questions.json")
        questions = all_hw[hw_key]["questions"]
        assert questions[0]["subject_type"] == "chinese_essay"
        assert questions[1]["subject_type"] == "chemistry_short"

    def test_create_form_has_subject_type_dropdown(self, client):
        """GET form should include subject_type dropdown options."""
        _ensure_login(client)
        resp = client.get("/teacher/homework/create")
        assert resp.status_code == 200
        assert b"q_subject_type" in resp.data
        assert b"physics_short" in resp.data
        assert b"chinese_essay" in resp.data
        assert b"math_calculation" in resp.data
