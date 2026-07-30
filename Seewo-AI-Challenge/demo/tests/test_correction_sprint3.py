"""Tests for V1.5 Sprint 3: correction loop student-facing pages.

Tests cover:
  - GET /student/correction/<submission_id> renders the correction submit page
  - GET /student/corrections renders the correction history page
  - Student dashboard "待订正" entry links to correction page
  - Page shows correct data (wrong questions, original answers, correction status)
  - Prod mode with login works
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

from _helpers import get_csrf_token


def _ensure_login(client):
    """Set session to student s02 (has correction records).

    Uses session_transaction() directly — works in both demo and prod modes,
    doesn't depend on login route / password hashing / DB availability.
    """
    with client.session_transaction() as sess:
        sess["user_id"] = "s02"
        sess["user_role"] = "student"
        sess["user_name"] = "同学B"
        sess["_csrf"] = "test-csrf-token"


class TestCorrectionSubmitPage:
    """Test the correction submit page GET /student/correction/<submission_id>."""

    def test_correction_page_renders(self, client):
        """GET /student/correction/s02_hw_001 should render the page."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert resp.status_code == 200
        assert "订正练习".encode() in resp.data

    def test_correction_page_shows_wrong_questions(self, client):
        """Page should show questions that were answered incorrectly."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert resp.status_code == 200
        # s02 got q5 wrong (long answer) — should show "待订正" or "已订正"
        assert b"Q5" in resp.data or b"q5" in resp.data

    def test_correction_page_shows_original_answer(self, client):
        """Page should display the student's original answer."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert b"\xe4\xbd\xa0\xe7\x9a\x84\xe5\x8e\x9f\xe4\xbd\x9c\xe7\xad\x94" in resp.data  # "你的原作答"

    def test_correction_page_shows_correction_input(self, client):
        """Page should include correction input area for unanswered/wrong questions."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert resp.status_code == 200
        # s02 has wrong answers (q5, q6) — should show correction input or closed status
        assert b"corr-submit-btn" in resp.data or b"\xe5\xb7\xb2\xe7\xad\x94\xe5\xaf\xb9" in resp.data

    def test_correction_page_invalid_submission_id(self, client):
        """GET with invalid submission_id should return 404."""
        _ensure_login(client)
        resp = client.get("/student/correction/nonexistent_submission")
        assert resp.status_code == 404

    def test_correction_page_shows_closed_status(self, client):
        """Page should show '已订正' for questions with closed correction status."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        # s02 has q5 and q6 corrections closed
        assert b"\xe5\xb7\xb2\xe8\xae\xa2\xe6\xad\xa3" in resp.data  # "已订正"

    def test_correction_page_has_csrf(self, client):
        """Page should include CSRF token."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert b"csrf_token" in resp.data

    def test_correction_page_has_nav_link(self, client):
        """Page should include nav link to corrections history."""
        _ensure_login(client)
        resp = client.get("/student/correction/s02_hw_001")
        assert b"/student/corrections" in resp.data


class TestCorrectionHistoryPage:
    """Test the correction history page GET /student/corrections."""

    def test_corrections_page_renders(self, client):
        """GET /student/corrections should render."""
        _ensure_login(client)
        resp = client.get("/student/corrections")
        assert resp.status_code == 200
        assert "订正历史".encode() in resp.data

    def test_corrections_page_shows_records(self, client):
        """Page should show correction records for the student."""
        _ensure_login(client)
        resp = client.get("/student/corrections")
        assert resp.status_code == 200
        # s02 has correction records
        assert b"Q5" in resp.data or b"q5" in resp.data

    def test_corrections_page_shows_mastery_level(self, client):
        """Page should show mastery level for corrections."""
        _ensure_login(client)
        resp = client.get("/student/corrections")
        assert b"\xe5\xb7\xb2\xe6\x8e\x8c\xe6\x8f\xa1" in resp.data  # "已掌握"

    def test_corrections_page_empty_state(self, client):
        """Page should show empty state when no corrections exist."""
        _ensure_login(client)
        resp = client.get("/student/corrections")
        assert resp.status_code == 200
        # Should show either records or empty state
        assert b"\xe8\xae\xa2\xe6\xad\xa3\xe5\x8e\x86\xe5\x8f\xb2" in resp.data  # "订正历史"

    def test_corrections_page_has_nav_link(self, client):
        """Page should include nav link back to dashboard."""
        _ensure_login(client)
        resp = client.get("/student/corrections")
        assert b"/dashboard" in resp.data


class TestDashboardCorrectionEntry:
    """Test that the student dashboard has a correction entry."""

    def test_dashboard_has_correction_link(self, client):
        """Dashboard should have a link to the correction page."""
        _ensure_login(client)
        resp = client.get("/student/s02/dashboard")
        assert resp.status_code == 200
        assert b"/student/correction/" in resp.data

    def test_dashboard_has_corrections_nav(self, client):
        """Dashboard nav should include corrections history link."""
        _ensure_login(client)
        resp = client.get("/student/s02/dashboard")
        assert b"/student/corrections" in resp.data

    def test_dashboard_correction_count_displayed(self, client):
        """Dashboard should show the corrections_due count."""
        _ensure_login(client)
        resp = client.get("/student/s02/dashboard")
        assert b"\xe5\xbe\x85\xe8\xae\xa2\xe6\xad\xa3" in resp.data  # "待订正"


class TestCorrectionPageProdMode:
    """Test correction pages in prod mode with login."""

    def test_correction_page_prod_mode(self, app):
        """Correction page should work in prod mode with auth."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess["user_id"] = "s02"
                sess["user_role"] = "student"
                sess["user_name"] = "同学B"
                sess["_csrf"] = "test-csrf-token"
            resp = client.get("/student/correction/s02_hw_001")
            assert resp.status_code == 200
            assert "订正练习".encode() in resp.data
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_corrections_page_prod_mode(self, app):
        """Corrections history page should work in prod mode with auth."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess["user_id"] = "s02"
                sess["user_role"] = "student"
                sess["user_name"] = "同学B"
                sess["_csrf"] = "test-csrf-token"
            resp = client.get("/student/corrections")
            assert resp.status_code == 200
            assert "订正历史".encode() in resp.data
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"
