"""OCR module tests — Sprint 2 (全栈代码审查官).

Covers:
    1. Module import + public API surface
    2. MockOCREngine deterministic output
    3. is_ocr_available / get_ocr_engine selection logic
    4. extract_text convenience function (mock mode)
    5. OCR → grading flow (OCR text fed into grade_long_answer)
    6. Flask /api/ocr/upload endpoint (mock mode)
    7. Flask /api/ocr/grade endpoint (OCR + grading integration)
    8. OCR_FORCE_MOCK env override
    9. PaddleOCREngine image preparation (base64 / bytes / data URI)
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

import pytest

# Ensure demo/ is on sys.path (conftest already does this, but be explicit)
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))


# ── 1. Module import + public API ─────────────────────────────────────
class TestOCRModuleImport:
    """Verify the OCR sub-package is importable and exposes its API."""

    def test_import_engine_ocr(self):
        """engine.ocr package imports without error."""
        from engine import ocr  # noqa: F401

    def test_public_api_exists(self):
        """All public functions are callable."""
        from engine import ocr

        assert callable(ocr.get_ocr_engine)
        assert callable(ocr.is_ocr_available)
        assert callable(ocr.extract_text)
        assert hasattr(ocr, "PaddleOCREngine")
        assert hasattr(ocr, "MockOCREngine")


# ── 2. MockOCREngine ──────────────────────────────────────────────────
class TestMockOCREngine:
    """MockOCREngine returns deterministic, well-shaped results."""

    def test_returns_dict_with_required_keys(self):
        from engine.ocr import MockOCREngine

        engine = MockOCREngine()
        result = engine.extract(b"fake image bytes", "long_answer")
        assert isinstance(result, dict)
        for key in ("text", "confidence", "provider", "lines", "question_type"):
            assert key in result, f"missing key: {key}"

    def test_provider_is_mock(self):
        from engine.ocr import MockOCREngine

        result = MockOCREngine().extract(b"x", "choice")
        assert result["provider"] == "mock"

    def test_deterministic_output(self):
        """Same input → same output (no randomness)."""
        from engine.ocr import MockOCREngine

        engine = MockOCREngine()
        r1 = engine.extract(b"img", "long_answer")
        r2 = engine.extract(b"img", "long_answer")
        assert r1 == r2

    def test_question_type_echoed(self):
        from engine.ocr import MockOCREngine

        for qt in ("choice", "fill_blank", "long_answer"):
            result = MockOCREngine().extract(b"img", qt)
            assert result["question_type"] == qt

    def test_choice_returns_short_text(self):
        """Choice-type mock should return a short answer (like 'A')."""
        from engine.ocr import MockOCREngine

        result = MockOCREngine().extract(b"img", "choice")
        assert len(result["text"]) <= 5

    def test_long_answer_returns_math_content(self):
        """Long-answer mock should contain math-like content."""
        from engine.ocr import MockOCREngine

        result = MockOCREngine().extract(b"img", "long_answer")
        assert len(result["text"]) > 10
        # Should look like a math derivation
        assert "f" in result["text"].lower() or "x" in result["text"].lower()


# ── 3. Engine selection ───────────────────────────────────────────────
class TestEngineSelection:
    """get_ocr_engine / is_ocr_available behave correctly."""

    def test_get_ocr_engine_returns_engine(self):
        from engine.ocr import get_ocr_engine, MockOCREngine, PaddleOCREngine

        engine = get_ocr_engine()
        assert isinstance(engine, (MockOCREngine, PaddleOCREngine))

    def test_get_ocr_engine_singleton(self):
        """get_ocr_engine returns the same instance on repeat calls."""
        from engine.ocr import get_ocr_engine

        e1 = get_ocr_engine()
        e2 = get_ocr_engine()
        assert e1 is e2

    def test_is_ocr_available_returns_bool(self):
        from engine.ocr import is_ocr_available

        assert isinstance(is_ocr_available(), bool)

    def test_force_mock_env(self, monkeypatch):
        """OCR_FORCE_MOCK=1 forces MockOCREngine even if paddleocr exists."""
        # Reset singleton
        import engine.ocr.paddle_ocr as mod

        monkeypatch.setattr(mod, "_FORCE_MOCK", True)
        monkeypatch.setattr(mod, "_engine_instance", None)

        from engine.ocr import get_ocr_engine, MockOCREngine, is_ocr_available

        assert is_ocr_available() is False
        engine = get_ocr_engine()
        assert isinstance(engine, MockOCREngine)

        # Cleanup: reset singleton for other tests
        monkeypatch.setattr(mod, "_FORCE_MOCK", False)
        monkeypatch.setattr(mod, "_engine_instance", None)


# ── 4. extract_text convenience function ─────────────────────────────
class TestExtractText:
    """extract_text works as a standalone entry point."""

    def test_returns_well_formed_dict(self):
        from engine.ocr import extract_text

        result = extract_text(b"fake", "long_answer")
        assert "text" in result
        assert "provider" in result
        assert "confidence" in result

    def test_accepts_base64_string(self):
        from engine.ocr import extract_text

        b64 = base64.b64encode(b"fake image").decode("ascii")
        result = extract_text(b64, "choice")
        assert "text" in result

    def test_accepts_data_uri(self):
        from engine.ocr import extract_text

        b64 = base64.b64encode(b"fake image").decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        result = extract_text(data_uri, "fill_blank")
        assert "text" in result


# ── 5. OCR → grading flow ────────────────────────────────────────────
class TestOCRToGradingFlow:
    """OCR output feeds into the grading engine correctly."""

    def test_ocr_text_can_be_graded_as_long_answer(self):
        """OCR-recognized text → grade_long_answer produces valid result."""
        from engine.ocr import MockOCREngine
        from engine.grader import grade_long_answer

        # Get mock OCR text
        ocr_result = MockOCREngine().extract(b"img", "long_answer")
        student_answer = ocr_result["text"]

        # Build a minimal question
        question = {
            "id": "q_ocr_test",
            "type": "long_answer",
            "stem": "求 f(x)=x³-3x 的单调区间",
            "score": 10,
            "answer": "f'(x)=3x²-3, x<-1递增, -1<x<1递减, x>1递增",
            "knowledge": "利用导数判断函数单调性",
            "steps": [
                {"step": 1, "content": "求导", "score": 3},
                {"step": 2, "content": "令f'(x)=0求根", "score": 3},
                {"step": 3, "content": "判断单调性", "score": 4},
            ],
        }

        result = grade_long_answer(student_answer, question, "s_ocr")
        assert "is_correct" in result
        assert "score" in result
        assert "step_results" in result
        assert isinstance(result["score"], (int, float))

    def test_ocr_text_choice_grade(self):
        """OCR-recognized choice answer → grade_choice."""
        from engine.ocr import MockOCREngine
        from engine.grader import grade_choice

        ocr_result = MockOCREngine().extract(b"img", "choice")
        result = grade_choice(ocr_result["text"], "B", {"score": 5})
        assert "is_correct" in result
        assert result["max_score"] == 5

    def test_ocr_text_fill_blank_grade(self):
        """OCR-recognized fill_blank answer → grade_fill_blank."""
        from engine.ocr import MockOCREngine
        from engine.grader import grade_fill_blank

        ocr_result = MockOCREngine().extract(b"img", "fill_blank")
        result = grade_fill_blank(ocr_result["text"], "42", {"score": 3})
        assert "is_correct" in result
        assert result["max_score"] == 3

    def test_full_ocr_to_grade_pipeline(self):
        """End-to-end: image bytes → OCR → grade → structured result."""
        from engine.ocr import extract_text
        from engine.grader import grade_long_answer

        # Simulate an uploaded image
        fake_image = base64.b64encode(b"answer sheet image").decode("ascii")
        ocr_result = extract_text(fake_image, "long_answer")
        assert ocr_result["text"]  # non-empty

        question = {
            "id": "q_pipeline",
            "type": "long_answer",
            "stem": "test",
            "score": 12,
            "answer": "test answer",
            "knowledge": "test",
            "steps": [{"step": 1, "content": "step1", "score": 12}],
        }
        grade = grade_long_answer(ocr_result["text"], question, "s_pipeline")
        assert grade["type"] == "long_answer"
        assert grade["max_score"] == 12


# ── 6. Flask /api/ocr/upload endpoint ─────────────────────────────────
class TestOCREndpoints:
    """Flask OCR upload + grade endpoints (mock mode)."""

    def _ensure_login(self, client):
        """Log in as teacher if in prod mode (DEMO_AUTH_OPEN=0)."""
        if os.environ.get("DEMO_AUTH_OPEN", "0") == "0":
            from _helpers import login
            login(client, "teacher", "teacher123")

    def test_ocr_upload_endpoint_exists(self, app):
        """The /api/ocr/upload route is registered."""
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/ocr/upload" in rules

    def test_ocr_grade_endpoint_exists(self, app):
        """The /api/ocr/grade route is registered."""
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/ocr/grade" in rules

    def test_ocr_upload_no_file_400(self, client):
        """POST /api/ocr/upload without a file returns 400."""
        self._ensure_login(client)
        resp = client.post("/api/ocr/upload", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_ocr_grade_no_file_400(self, client):
        """POST /api/ocr/grade without a file returns 400."""
        self._ensure_login(client)
        resp = client.post("/api/ocr/grade", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400

    def test_ocr_upload_success(self, client):
        """POST /api/ocr/upload with a fake image returns OCR result."""
        self._ensure_login(client)
        from io import BytesIO

        data = {
            "file": (BytesIO(b"fake image content"), "test.jpg"),
            "question_type": "long_answer",
            "question_id": "q_test",
        }
        resp = client.post(
            "/api/ocr/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "text" in body
        assert "provider" in body
        assert body["question_id"] == "q_test"

    def test_ocr_grade_success(self, client):
        """POST /api/ocr/grade with image returns both OCR and grade results."""
        self._ensure_login(client)
        from io import BytesIO

        data = {
            "file": (BytesIO(b"fake image content"), "answer.jpg"),
            "question_type": "long_answer",
            "question_id": "q5",
            "student_id": "s01",
        }
        resp = client.post(
            "/api/ocr/grade",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "ocr_result" in body
        assert "grade_result" in body
        assert "text" in body["ocr_result"]
        assert "is_correct" in body["grade_result"]


# ── 7. PaddleOCREngine image preparation ─────────────────────────────
class TestPaddleImagePrep:
    """PaddleOCREngine._prepare_image handles various input formats."""

    def test_prepare_base64_string(self):
        from engine.ocr.paddle_ocr import PaddleOCREngine

        b64 = base64.b64encode(b"fake").decode("ascii")
        result = PaddleOCREngine._prepare_image(b64)
        # Should return None for invalid image data (not crash)
        # or a numpy array if PIL can decode (unlikely for "fake")
        assert result is None or hasattr(result, "shape")

    def test_prepare_raw_bytes(self):
        from engine.ocr.paddle_ocr import PaddleOCREngine

        result = PaddleOCREngine._prepare_image(b"fake bytes")
        assert result is None or hasattr(result, "shape")

    def test_prepare_data_uri(self):
        from engine.ocr.paddle_ocr import PaddleOCREngine

        b64 = base64.b64encode(b"fake").decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"
        result = PaddleOCREngine._prepare_image(data_uri)
        assert result is None or hasattr(result, "shape")

    def test_prepare_invalid_string_returns_none(self):
        from engine.ocr.paddle_ocr import PaddleOCREngine

        result = PaddleOCREngine._prepare_image("not a path or base64!!!")
        assert result is None

    def test_prepare_none_returns_none(self):
        from engine.ocr.paddle_ocr import PaddleOCREngine

        result = PaddleOCREngine._prepare_image(None)  # type: ignore
        assert result is None


# ── 8. PaddleOCREngine graceful fallback ──────────────────────────────
class TestPaddleFallback:
    """PaddleOCREngine degrades to mock when model unavailable."""

    def test_paddle_engine_falls_back_to_mock(self):
        """When PaddleOCR can't load, extract() returns mock result."""
        from engine.ocr.paddle_ocr import PaddleOCREngine

        engine = PaddleOCREngine()
        # _ensure_model will fail because we don't init the real model
        result = engine.extract(b"fake", "long_answer")
        # Should return a valid dict (either from mock fallback or paddle)
        assert "text" in result
        assert "provider" in result

    def test_paddle_parse_empty_result(self):
        """_parse_paddle_result handles empty/None gracefully."""
        from engine.ocr.paddle_ocr import PaddleOCREngine

        lines, confs = PaddleOCREngine._parse_paddle_result(None)
        assert lines == []
        assert confs == []

        lines, confs = PaddleOCREngine._parse_paddle_result([])
        assert lines == []
        assert confs == []

        lines, confs = PaddleOCREngine._parse_paddle_result([[]])
        assert lines == []
        assert confs == []

    def test_paddle_parse_valid_result(self):
        """_parse_paddle_result correctly parses PaddleOCR v3 format."""
        from engine.ocr.paddle_ocr import PaddleOCREngine

        fake_result = [[
            [[[0, 0], [100, 0], [100, 30], [0, 30]], ("f'(x) = 3x²", 0.95)],
            [[[0, 40], [100, 40], [100, 70], [0, 70]], ("令 f'(x)=0", 0.88)],
        ]]
        lines, confs = PaddleOCREngine._parse_paddle_result(fake_result)
        assert len(lines) == 2
        assert lines[0] == "f'(x) = 3x²"
        assert confs[0] == pytest.approx(0.95)
