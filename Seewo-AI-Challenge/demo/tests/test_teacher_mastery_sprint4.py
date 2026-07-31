"""Tests for V1.5 Sprint 4: teacher class mastery dashboard.

Tests cover:
  - GET /teacher/mastery renders the dashboard page
  - Page shows per-homework → per-question mastery distribution
  - Page shows per-student mastery progress + correction activity
  - Weakest questions (Top 3) are highlighted
  - Click-to-drill shows per-student details per question
  - API GET /api/teacher/mastery returns correct data structure
  - Prod mode with login works
  - emotional_feedback display in correction submit page
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


def _ensure_teacher_login(client):
    """Set session to teacher role for testing.

    Uses session_transaction() — works in both demo and prod modes.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "teacher"
        sess["user_role"] = "teacher"
        sess["user_name"] = "李老师"
        sess["_csrf"] = "test-csrf-token"


def _ensure_student_login(client):
    """Set session to student s02."""
    with client.session_transaction() as sess:
        sess["user_id"] = "s02"
        sess["user_role"] = "student"
        sess["user_name"] = "同学B"
        sess["_csrf"] = "test-csrf-token"


class TestTeacherMasteryPage:
    """Test the teacher mastery dashboard page GET /teacher/mastery."""

    def test_mastery_page_renders(self, client):
        """GET /teacher/mastery should render the page."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        assert "班级掌握度看板".encode() in resp.data

    def test_mastery_page_shows_homeworks(self, client):
        """Page should list homeworks with questions."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        # hw_001 title "函数单调性与极值" should appear
        assert b"\xe5\x87\xbd\xe6\x95\xb0\xe5\x8d\x95\xe8\xb0\x83\xe6\x80\xa7" in resp.data  # "函数单调性"

    def test_mastery_page_shows_mastery_distribution(self, client):
        """Page should show mastery distribution counts (mastered/partial/not_mastered/uncorrected)."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        # Should contain distribution numbers
        assert b"mastered" in resp.data or b"\xe5\xb7\xb2\xe6\x8e\x8c\xe6\x8f\xa1" in resp.data  # "已掌握"

    def test_mastery_page_shows_students(self, client):
        """Page should show per-student mastery progress."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        assert b"\xe5\xad\xa6\xe7\x94\x9f\xe6\x8e\x8c\xe6\x8f\xa1\xe5\xba\xa6\xe8\xbf\x9b\xe5\xba\xa6" in resp.data  # "学生掌握度进度"

    def test_mastery_page_shows_weakest_questions(self, client):
        """Page should highlight Top 3 weakest questions."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        assert b"\xe8\x96\x84\xe5\xbc\xb1\xe9\xa2\x98\xe7\x9b\xae" in resp.data  # "薄弱题目"

    def test_mastery_page_has_drilldown(self, client):
        """Page should include clickable drilldown for per-student details."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        assert b"toggleDetail" in resp.data

    def test_mastery_page_has_nav_link(self, client):
        """Teacher nav should include mastery dashboard link."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert b"/teacher/mastery" in resp.data

    def test_mastery_page_has_color_legend(self, client):
        """Page should show color legend for mastery levels."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert b"bg-green-500" in resp.data
        assert b"bg-amber-500" in resp.data
        assert b"bg-red-500" in resp.data

    def test_mastery_page_shows_correction_counts(self, client):
        """Page should show correction count / closed count / pending count per student."""
        _ensure_teacher_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code == 200
        assert b"\xe8\xae\xa2\xe6\xad\xa3\xe6\x80\xbb\xe6\x95\xb0" in resp.data  # "订正总数"
        assert b"\xe5\xb7\xb2\xe9\x97\xad\xe7\x8e\xaf" in resp.data  # "已闭环"

    def test_mastery_page_student_denied(self, client):
        """Student role should not access teacher mastery page (403 or redirect)."""
        _ensure_student_login(client)
        resp = client.get("/teacher/mastery")
        assert resp.status_code in (302, 403)


class TestTeacherMasteryAPI:
    """Test the API endpoint GET /api/teacher/mastery."""

    def test_api_returns_json(self, client):
        """API should return valid JSON with ok=true."""
        _ensure_teacher_login(client)
        resp = client.get("/api/teacher/mastery")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_api_has_homeworks(self, client):
        """API response should include homeworks array."""
        _ensure_teacher_login(client)
        resp = client.get("/api/teacher/mastery")
        data = resp.get_json()
        assert "homeworks" in data
        assert len(data["homeworks"]) > 0

    def test_api_has_students(self, client):
        """API response should include students array."""
        _ensure_teacher_login(client)
        resp = client.get("/api/teacher/mastery")
        data = resp.get_json()
        assert "students" in data
        assert len(data["students"]) > 0

    def test_api_mastery_distribution(self, client):
        """Each question should have mastery_distribution with 4 keys."""
        _ensure_teacher_login(client)
        resp = client.get("/api/teacher/mastery")
        data = resp.get_json()
        hw = data["homeworks"][0]
        q = hw["questions"][0]
        assert "mastery_distribution" in q
        md = q["mastery_distribution"]
        assert "mastered" in md
        assert "partial" in md
        assert "not_mastered" in md
        assert "uncorrected" in md

    def test_api_student_fields(self, client):
        """Each student should have correction_count, closed_count, mastery_rate."""
        _ensure_teacher_login(client)
        resp = client.get("/api/teacher/mastery")
        data = resp.get_json()
        s = data["students"][0]
        assert "student_id" in s
        assert "name" in s
        assert "correction_count" in s
        assert "closed_count" in s
        assert "mastery_rate" in s

    def test_api_weakest_flag(self, client):
        """Top-3 lowest mastery rate questions should have weakest=true."""
        _ensure_teacher_login(client)
        resp = client.get("/api/teacher/mastery")
        data = resp.get_json()
        hw = data["homeworks"][0]
        weakest = [q for q in hw["questions"] if q.get("weakest")]
        assert len(weakest) <= 3

    def test_api_student_denied(self, client):
        """Student role should not access teacher API."""
        _ensure_student_login(client)
        resp = client.get("/api/teacher/mastery")
        assert resp.status_code in (302, 403)


class TestEmotionalFeedbackDisplay:
    """Test emotional_feedback display in student correction submit page."""

    def test_correction_page_has_feedback_display_js(self, client):
        """Correction submit page should include emotional_feedback display JS."""
        _ensure_student_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert resp.status_code == 200
        assert b"emotional_feedback" in resp.data
        assert b"showEmotionalFeedback" in resp.data

    def test_correction_page_has_laoshi_jiyu(self, client):
        """Correction submit page should include 老师寄语 label for emotional feedback."""
        _ensure_student_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert resp.status_code == 200
        assert b"\xe8\x80\x81\xe5\xb8\x88\xe5\xaf\x84\xe8\xaf\xad" in resp.data  # "老师寄语"


class TestMasteryPageProdMode:
    """Test mastery page in prod mode with login."""

    def test_mastery_page_prod_mode(self, app):
        """Mastery page should work in prod mode with teacher auth."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess["user_id"] = "teacher"
                sess["user_role"] = "teacher"
                sess["user_name"] = "李老师"
                sess["_csrf"] = "test-csrf-token"
            resp = client.get("/teacher/mastery")
            assert resp.status_code == 200
            assert "班级掌握度看板".encode() in resp.data
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_mastery_page_prod_redirect_anonymous(self, app):
        """Anonymous access should redirect to login in prod mode."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            client = app.test_client()
            resp = client.get("/teacher/mastery")
            assert resp.status_code == 302
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"
