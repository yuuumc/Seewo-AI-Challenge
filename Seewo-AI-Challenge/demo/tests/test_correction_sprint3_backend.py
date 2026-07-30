"""Sprint 3 订正闭环后端测试 — 全栈代码审查官.

覆盖:
    1. correction_grader 引擎（mock 模式）：掌握度判定 + 反馈生成
    2. POST /api/correction/submit：订正提交 → 批改 → 持久化
    3. GET /api/correction/list：订正列表 + 待订正计数
    4. 权限边界：学生 A 不能提交学生 B 的订正
    5. 掌握度追踪：多次订正取最新
    6. 数据模型兼容：corrections.json 结构正确
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from io import BytesIO
from pathlib import Path

import pytest

_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from _helpers import get_csrf_token, login


# ── Fixture: 备份/恢复 corrections.json ──────────────────────────────
@pytest.fixture(autouse=True)
def _restore_corrections():
    """每个测试前后备份/恢复 corrections.json，避免测试间数据污染."""
    corrections_path = _DEMO_DIR / "data" / "corrections.json"
    backup = None
    if corrections_path.exists():
        with open(corrections_path, "r", encoding="utf-8") as f:
            backup = f.read()
    yield
    if backup is not None:
        with open(corrections_path, "w", encoding="utf-8") as f:
            f.write(backup)


def _ensure_login(client):
    """Log in as student if in prod mode."""
    if os.environ.get("DEMO_AUTH_OPEN", "0") == "0":
        login(client, "s02", "student123")


def _ensure_login_student(client, username="s02"):
    """Log in as a specific student."""
    if os.environ.get("DEMO_AUTH_OPEN", "0") == "0":
        login(client, username, "student123")


def _ensure_login_teacher(client):
    """Log in as teacher."""
    if os.environ.get("DEMO_AUTH_OPEN", "0") == "0":
        login(client, "teacher", "teacher123")


# ── 1. correction_grader 引擎 ─────────────────────────────────────────
class TestCorrectionGrader:
    """订正对比批改引擎单元测试."""

    def test_choice_correct(self):
        from engine.correction_grader import grade_correction, MASTERY_MASTERED

        question = {"id": "q1", "type": "choice", "answer": "B", "score": 5, "knowledge": "算术"}
        result = grade_correction(question, "A", {"is_correct": False}, "B", "s01")
        assert result["mastery_level"] == MASTERY_MASTERED
        assert result["is_correct"] is True
        assert result["graded_by"] == "mock"

    def test_choice_wrong(self):
        from engine.correction_grader import grade_correction, MASTERY_NOT_MASTERED

        question = {"id": "q1", "type": "choice", "answer": "B", "score": 5, "knowledge": "算术"}
        result = grade_correction(question, "A", {"is_correct": False}, "C", "s01")
        assert result["mastery_level"] == MASTERY_NOT_MASTERED
        assert result["is_correct"] is False

    def test_fill_blank_correct(self):
        from engine.correction_grader import grade_correction, MASTERY_MASTERED

        question = {"id": "q3", "type": "fill_blank", "answer": "2", "score": 3, "knowledge": "导数"}
        result = grade_correction(question, "0", {"is_correct": False}, "2", "s01")
        assert result["mastery_level"] == MASTERY_MASTERED

    def test_fill_blank_wrong(self):
        from engine.correction_grader import grade_correction, MASTERY_NOT_MASTERED

        question = {"id": "q3", "type": "fill_blank", "answer": "2", "score": 3, "knowledge": "导数"}
        result = grade_correction(question, "0", {"is_correct": False}, "5", "s01")
        assert result["mastery_level"] == MASTERY_NOT_MASTERED

    def test_long_answer_mastered(self):
        from engine.correction_grader import grade_correction, MASTERY_MASTERED

        question = {
            "id": "q5", "type": "long_answer", "score": 12,
            "answer": "f'(x)=3x²-6ax+3a²=3(x-a)², (x-a)²≥0, 单调递增",
            "knowledge": "利用导数判断函数单调性",
            "steps": [
                {"step": 1, "content": "f'(x)=3x²-6ax+3a²", "score": 3},
                {"step": 2, "content": "=3(x-a)²", "score": 3},
                {"step": 3, "content": "≥0 单调递增", "score": 6},
            ],
        }
        correction = "f'(x)=3x²-6ax+3a²=3(x-a)² 因为(x-a)²≥0 所以f'(x)≥0 单调递增"
        result = grade_correction(question, "不会做", {"is_correct": False}, correction, "s01")
        assert result["mastery_level"] == MASTERY_MASTERED
        assert result["is_correct"] is True

    def test_long_answer_partial(self):
        from engine.correction_grader import grade_correction, MASTERY_PARTIAL

        question = {
            "id": "q5", "type": "long_answer", "score": 12,
            "answer": "f'(x)=3x²-6ax+3a²=3(x-a)², (x-a)²≥0, 单调递增",
            "knowledge": "利用导数判断函数单调性",
            "steps": [
                {"step": 1, "content": "f'(x)=3x²-6ax+3a²", "score": 3},
                {"step": 2, "content": "=3(x-a)²", "score": 3},
                {"step": 3, "content": "≥0 单调递增", "score": 6},
            ],
        }
        # Only has partial steps but no conclusion
        correction = "f'(x)=3x²-6ax+3a² 我算到这里了"
        result = grade_correction(question, "不会做", {"is_correct": False}, correction, "s01")
        assert result["mastery_level"] == MASTERY_PARTIAL

    def test_long_answer_not_mastered(self):
        from engine.correction_grader import grade_correction, MASTERY_NOT_MASTERED

        question = {
            "id": "q5", "type": "long_answer", "score": 12,
            "answer": "f'(x)=3x²-6ax+3a²=3(x-a)², 单调递增",
            "knowledge": "导数",
            "steps": [{"step": 1, "content": "f'(x)=3x²-6ax+3a²", "score": 12}],
        }
        result = grade_correction(question, "x", {"is_correct": False}, "我猜答案是0", "s01")
        assert result["mastery_level"] == MASTERY_NOT_MASTERED

    def test_empty_correction(self):
        from engine.correction_grader import grade_correction, MASTERY_NOT_MASTERED

        question = {"id": "q1", "type": "long_answer", "answer": "x", "knowledge": "test", "steps": []}
        result = grade_correction(question, "A", {"is_correct": False}, "", "s01")
        assert result["mastery_level"] == MASTERY_NOT_MASTERED

    def test_response_structure(self):
        """返回结果包含所有契约要求的字段."""
        from engine.correction_grader import grade_correction

        question = {"id": "q1", "type": "choice", "answer": "B", "score": 5, "knowledge": "算术"}
        result = grade_correction(question, "A", {"is_correct": False}, "B", "s01")
        for key in ("mastery_level", "is_correct", "comparison", "feedback", "encouragement", "next_steps", "graded_by"):
            assert key in result, f"missing key: {key}"

    def test_encouragement_not_generic(self):
        """鼓励语应包含知识点，不是空洞赞美."""
        from engine.correction_grader import grade_correction

        question = {"id": "q1", "type": "choice", "answer": "B", "score": 5, "knowledge": "二次函数"}
        result = grade_correction(question, "A", {"is_correct": False}, "B", "s01")
        assert "二次函数" in result["encouragement"]
        assert "你真棒" not in result["encouragement"]

    def test_get_latest_mastery(self):
        from engine.correction_grader import get_latest_mastery, MASTERY_MASTERED

        attempts = [
            {"attempt": 1, "mastery_level": "not_mastered"},
            {"attempt": 2, "mastery_level": "partial"},
            {"attempt": 3, "mastery_level": MASTERY_MASTERED},
        ]
        assert get_latest_mastery(attempts) == MASTERY_MASTERED

    def test_get_latest_mastery_empty(self):
        from engine.correction_grader import get_latest_mastery, MASTERY_NOT_MASTERED

        assert get_latest_mastery([]) == MASTERY_NOT_MASTERED


# ── 2. POST /api/correction/submit ────────────────────────────────────
class TestCorrectionSubmitAPI:
    """订正提交端点测试."""

    def test_endpoint_exists(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/correction/submit" in rules

    def test_submit_choice_correct(self, client):
        """提交选择题订正（正确）→ mastered."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "D",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert body["mastery_level"] == "mastered"
        assert body["is_correct"] is True

    def test_submit_choice_wrong(self, client):
        """提交选择题订正（错误）→ not_mastered."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "C",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["mastery_level"] == "not_mastered"
        assert body["is_correct"] is False

    def test_submit_fill_blank(self, client):
        """提交填空题订正."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q3",
            "correction_text": "2",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "mastery_level" in body

    def test_submit_long_answer(self, client):
        """提交解答题订正."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q5",
            "correction_text": "f'(x)=3x²-6ax+3a²=3(x-a)² 因为(x-a)²≥0 所以单调递增",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "comparison" in body
        assert "encouragement" in body

    def test_submit_missing_fields(self, client):
        """缺少必填字段 → 400."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 400

    def test_submit_empty_correction(self, client):
        """空订正文本 → 400."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 400

    def test_submit_invalid_submission(self, client):
        """不存在的 submission_id → 404."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "nonexistent",
            "question_id": "q1",
            "correction_text": "A",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 404

    def test_submit_invalid_question(self, client):
        """不存在的 question_id → 404."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q_nonexistent",
            "correction_text": "A",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 404


# ── 3. GET /api/correction/list ───────────────────────────────────────
class TestCorrectionListAPI:
    """订正列表端点测试."""

    def test_endpoint_exists(self, app):
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/correction/list" in rules

    def test_list_returns_corrections(self, client):
        """GET /api/correction/list 返回订正列表."""
        _ensure_login(client)
        resp = client.get("/api/correction/list?student_id=s02")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        assert "corrections" in body
        assert "pending_count" in body
        assert isinstance(body["corrections"], list)
        assert isinstance(body["pending_count"], int)

    def test_list_has_existing_corrections(self, client):
        """s02 已有订正记录（corrections.json 预置）."""
        _ensure_login(client)
        resp = client.get("/api/correction/list?student_id=s02")
        body = resp.get_json()
        # s02 has corrections for q5 and q6 in the preset data
        assert len(body["corrections"]) >= 1
        first = body["corrections"][0]
        assert "question_id" in first
        assert "mastery_level" in first
        assert "status" in first


# ── 4. 权限边界 ───────────────────────────────────────────────────────
class TestPermissionBoundary:
    """学生 A 不能提交学生 B 的订正."""

    @pytest.mark.skipif(
        os.environ.get("DEMO_AUTH_OPEN", "0") == "1",
        reason="权限边界测试需要 PROD 模式（DEMO_AUTH_OPEN=0）",
    )
    def test_student_cannot_submit_others_correction(self, client):
        """登录 s01，尝试提交 s02 的订正 → 403."""
        # Use session_transaction directly (more robust than login route)
        with client.session_transaction() as sess:
            sess["user_id"] = "s01"
            sess["user_role"] = "student"
            sess["user_name"] = "同学A"
            sess["_csrf"] = "test-csrf-token"
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "D",
        }, headers={"X-CSRF-Token": "test-csrf-token"})
        assert resp.status_code == 403

    def test_teacher_can_submit_for_anyone(self, client):
        """教师可以提交任何学生的订正（管理功能）."""
        _ensure_login_teacher(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "D",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True


# ── 5. 掌握度追踪 + 持久化 ────────────────────────────────────────────
class TestMasteryTracking:
    """多次订正掌握度追踪 + 持久化."""

    def test_second_submission_increments_attempt(self, client):
        """同一题目第二次订正，attempt 序号递增."""
        _ensure_login(client)
        token = get_csrf_token(client)

        # First submission
        client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "C",
        }, headers={"X-CSRF-Token": token})

        # Second submission (correct this time)
        resp2 = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q1",
            "correction_text": "D",
        }, headers={"X-CSRF-Token": token})

        assert resp2.status_code == 200
        body2 = resp2.get_json()
        assert body2["mastery_level"] == "mastered"

        # Verify in list
        list_resp = client.get("/api/correction/list?student_id=s02")
        list_body = list_resp.get_json()
        q1_corr = [c for c in list_body["corrections"] if c["question_id"] == "q1"]
        if q1_corr:
            assert q1_corr[0]["attempt_count"] >= 2
            assert q1_corr[0]["mastery_level"] == "mastered"

    def test_mastered_closes_loop(self, client):
        """mastered 后 status 置为 closed."""
        _ensure_login(client)
        token = get_csrf_token(client)
        resp = client.post("/api/correction/submit", json={
            "submission_id": "s02_hw_001",
            "question_id": "q2",
            "correction_text": "A",
        }, headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
        assert resp.get_json()["mastery_level"] == "mastered"

        list_resp = client.get("/api/correction/list?student_id=s02")
        q2_corr = [c for c in list_resp.get_json()["corrections"] if c["question_id"] == "q2"]
        if q2_corr:
            assert q2_corr[0]["status"] == "closed"
