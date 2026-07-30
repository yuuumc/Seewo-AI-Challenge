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
