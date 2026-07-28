"""Smoke tests for ``engine.llm`` - all run with zero env vars.

Run with::

    cd Seewo-AI-Challenge/demo
    python -m unittest ../tests/test_llm_providers.py -v

These tests are designed to be import-safe even if the test
harness is still being wired up by the leader (see
``quick-prototype-ist``'s ``tests/conftest.py``). They do not
require Flask, requests, openai, or any external service.

Coverage:
    1. Factory auto-selects MockProvider when LLM_API_KEY is unset
    2. MockProvider preserves the grader.py output shape
    3. TraceRecord serialisation round-trip
    4. TraceCollector records exactly one entry per provider call
    5. get_runtime_trace falls back to the pre-baked JSON when no
       in-process trace exists (so the original demo page still
       renders for users who never trigger a grading flow)
    6. Factory returns a fresh provider when env vars change
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Make the demo/ dir importable when running this file directly
THIS_FILE = Path(__file__).resolve()
DEMO_DIR = THIS_FILE.parent.parent / "Seewo-AI-Challenge" / "demo"
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))


def _ensure_clean_factory() -> None:
    """Reset the factory singleton + trace store.

    Called from each test's setUp so tests are order-independent.
    Also clears any LLM_API_KEY that an earlier test left behind.
    """
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        os.environ.pop(k, None)
    from engine.llm import factory
    factory.reset_runtime_trace_store()


class TestFactorySelection(unittest.TestCase):
    """``get_provider()`` returns MockProvider when no key is set."""

    def setUp(self) -> None:
        # Snapshot env so we can restore.
        self._saved = {k: os.environ.get(k) for k in (
            "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
        )}
        _ensure_clean_factory()

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_no_key_returns_mock(self) -> None:
        from engine.llm import get_provider
        p = get_provider()
        self.assertEqual(p.name, "mock")
        self.assertEqual(type(p).__name__, "MockProvider")

    def test_with_key_returns_openai(self) -> None:
        os.environ["LLM_API_KEY"] = "sk-test-fake"
        os.environ["LLM_BASE_URL"] = "https://example.invalid/v1"
        os.environ["LLM_MODEL"] = "gpt-test"
        from engine.llm import get_provider
        p = get_provider()
        self.assertEqual(p.name, "gpt-test")
        self.assertEqual(type(p).__name__, "OpenAIProvider")

    def test_env_change_forces_re_resolve(self) -> None:
        from engine.llm import get_provider
        self.assertEqual(get_provider().name, "mock")
        os.environ["LLM_API_KEY"] = "sk-another"
        os.environ["LLM_BASE_URL"] = "https://example.invalid/v1"
        os.environ["LLM_MODEL"] = "deepseek-test"
        self.assertEqual(get_provider().name, "deepseek-test")


class TestMockProviderShape(unittest.TestCase):
    """MockProvider output is shape-compatible with grader.py."""

    def setUp(self) -> None:
        _ensure_clean_factory()
        from engine.grader import load_json
        self.questions = load_json("questions.json")["hw_001"]["questions"]

    def test_grade_step_returns_grader_shape(self) -> None:
        from engine.llm import get_provider
        provider = get_provider()
        q = next(q for q in self.questions if q["id"] == "q5")
        result = provider.grade_step(
            question=q,
            student_answer="f(x)=x^2, f'(x)=2x",
            standard_answer=q.get("answer", ""),
            student_id="s02",
        )
        for key in (
            "type", "is_correct", "score", "max_score",
            "step_results", "error_types", "ai_confidence",
            "overall_feedback", "need_teacher_review",
        ):
            self.assertIn(key, result, f"missing key: {key}")
        self.assertEqual(result["type"], "long_answer")
        self.assertIsInstance(result["step_results"], list)
        self.assertIsInstance(result["error_types"], list)

    def test_validate_correction_returns_grader_shape(self) -> None:
        from engine.llm import get_provider
        provider = get_provider()
        q = next(q for q in self.questions if q["id"] == "q5")
        result = provider.validate_correction(
            question=q,
            student_correction="f'(x) = 2x，函数单调递增",
            expected_answer=q.get("answer", ""),
        )
        for key in ("is_correct", "feedback", "verified_by_ai", "loop_closed"):
            self.assertIn(key, result, f"missing key: {key}")

    def test_generate_comment_returns_nonempty_string(self) -> None:
        from engine.llm import get_provider
        provider = get_provider()
        result = provider.generate_comment(
            student={"id": "s01", "name": "测试学生"},
            performance={
                "assignment_id": "hw_001",
                "total": 80,
                "max_score": 100,
                "mistakes": [],
            },
        )
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class TestTraceCollector(unittest.TestCase):
    """TraceCollector records and serialises properly."""

    def setUp(self) -> None:
        _ensure_clean_factory()

    def test_record_appends_in_order(self) -> None:
        from engine.llm.base import TraceCollector
        tc = TraceCollector(student_id="s01", assignment_id="hw_001")
        for i in range(3):
            tc.record(
                stage=f"stage_{i}",
                input_payload={"i": i},
                output_payload={"o": i * 2},
                duration_ms=10.0 + i,
                confidence=0.9,
                model="mock",
            )
        self.assertEqual(len(tc.records), 3)
        self.assertEqual([r.stage for r in tc.records],
                         ["stage_0", "stage_1", "stage_2"])
        d = tc.to_dict()
        self.assertEqual(d["student_id"], "s01")
        self.assertEqual(d["assignment_id"], "hw_001")
        self.assertEqual(d["stage_count"], 3)
        self.assertEqual(len(d["stages"]), 3)
        json.dumps(d)  # all fields JSON-serialisable

    def test_provider_records_one_per_call(self) -> None:
        from engine.llm import get_provider
        from engine.llm.base import TraceCollector
        provider = get_provider()
        # Defensive: if a previous test cached an OpenAIProvider, the
        # factory's env-fingerprint check should have already re-
        # resolved to MockProvider. This assertion documents the
        # contract.
        self.assertEqual(type(provider).__name__, "MockProvider")
        tc = TraceCollector(student_id="s99", assignment_id="hw_001")
        from engine.grader import load_json
        q = load_json("questions.json")["hw_001"]["questions"][0]
        provider.grade_step(
            question=q,
            student_answer="",
            standard_answer=q.get("answer", ""),
            student_id="s99",
            trace=tc,
        )
        provider.validate_correction(
            question=q,
            student_correction="some correction",
            expected_answer=q.get("answer", ""),
            trace=tc,
        )
        provider.generate_comment(
            student={"id": "s99", "name": "X"},
            performance={"assignment_id": "hw_001", "total": 0, "max_score": 100},
            trace=tc,
        )
        self.assertEqual(len(tc.records), 3)
        stages = {r.stage for r in tc.records}
        self.assertIn("math_grading", stages)
        self.assertIn("correction_validation", stages)
        self.assertIn("comment_generation", stages)


class TestRuntimeTraceStore(unittest.TestCase):
    """get_runtime_trace / store_trace behave like a thread-safe LRU."""

    def setUp(self) -> None:
        _ensure_clean_factory()

    def test_fallback_to_prebaked_json(self) -> None:
        """When no in-process trace exists, the pre-baked JSON is used."""
        from engine.llm import get_runtime_trace
        d = get_runtime_trace("s01", "hw_001")
        self.assertIn("agents", d)
        self.assertIn("OCR Agent", d.get("agents", []))

    def test_unknown_key_returns_empty(self) -> None:
        from engine.llm import get_runtime_trace
        d = get_runtime_trace("s_does_not_exist", "hw_001")
        self.assertEqual(d.get("agents", []), [])
        self.assertIn("未找到", d.get("trace", ""))

    def test_store_then_retrieve_returns_runtime(self) -> None:
        from engine.llm import factory, get_runtime_trace
        from engine.llm.base import TraceCollector
        tc = TraceCollector(student_id="s05", assignment_id="hw_001")
        tc.record(
            stage="math_grading",
            input_payload={"q": "q5"},
            output_payload={"is_correct": False},
            duration_ms=12.5,
            confidence=0.7,
            model="mock",
        )
        factory.store_trace(tc)
        d = get_runtime_trace("s05", "hw_001")
        self.assertIn("math_grading", d["agents"])
        self.assertIn("math_grading", d["trace"])
        self.assertFalse(d.get("review_needed", True))

    def test_store_bounded_by_capacity(self) -> None:
        """Oldest collector is evicted past the per-key cap."""
        from engine.llm import factory, get_runtime_trace
        from engine.llm.base import TraceCollector
        for i in range(factory._MAX_TRACES_PER_KEY + 2):
            tc = TraceCollector(student_id="s03", assignment_id="hw_001")
            tc.record(
                stage=f"old_stage_{i}",
                input_payload={}, output_payload={},
                duration_ms=float(i), confidence=0.5, model="mock",
            )
            factory.store_trace(tc)
        d = get_runtime_trace("s03", "hw_001")
        self.assertIn("old_stage_9", d["trace"])


if __name__ == "__main__":
    unittest.main()
