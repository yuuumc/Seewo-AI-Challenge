"""Mock LLM provider - delegates to the existing rule engine.

This provider preserves the demo behaviour bit-for-bit. It is the
default selection when ``LLM_API_KEY`` is not set, and is also the
fallback target when the real provider fails after all retries.

The implementation is intentionally thin: rather than re-implement
the rule engine here, we delegate to the existing
``engine.grader`` functions. The ``TraceRecord`` written per call
is the only observable difference vs. the pre-LLM era.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from engine.llm.base import LLMProvider, TraceCollector
from engine.llm.pseudonym import pseudonymize_student_id


def _mock_multi_subject_grade(
    question: Dict[str, Any],
    student_answer: str,
    student_id: str,
) -> Dict[str, Any] | None:
    """Sprint 2: produce a structured mock result for non-math subjects.

    Uses the ``MOCK_SAMPLES`` fixtures from ``tests._multi_subject_fixtures``
    to return an ``expected_analysis``-shaped dict when the question's
    ``subject_type`` matches one of the 6 non-math subjects. Returns
    ``None`` when no fixture matches, so the caller falls back to the
    rule engine.

    The returned dict is shape-compatible with ``grade_long_answer()``:
    ``type`` / ``is_correct`` / ``score`` / ``max_score`` /
    ``step_results`` / ``error_types`` / ``ai_confidence`` /
    ``overall_feedback`` / ``need_teacher_review`` / ``student_answer``
    / ``correct_answer``.
    """
    subject_type = question.get("subject_type")
    if not subject_type:
        return None

    try:
        from tests._multi_subject_fixtures import MOCK_SAMPLES
    except ImportError:
        return None

    # Find a fixture matching this subject_type
    sample = None
    for s in MOCK_SAMPLES:
        if s["subject_type"] == subject_type:
            sample = s
            break
    if sample is None:
        return None

    ea = sample["expected_analysis"]
    max_score = float(question.get("score", sample["max_score"]))

    # Determine score: count correct steps, proportional to max_score
    step_results = ea["step_results"]
    correct_count = sum(1 for sr in step_results if sr.get("correct"))
    total_steps = len(step_results)
    if total_steps > 0:
        ratio = correct_count / total_steps
    else:
        ratio = 0.0
    # Full score only if all steps correct and no error types
    is_correct = len(ea["error_types"]) == 0 and correct_count == total_steps
    if is_correct:
        score = max_score
    else:
        score = round(max_score * ratio, 1)

    return {
        "type": "long_answer",
        "student_answer": student_answer,
        "correct_answer": question.get("answer", ""),
        "is_correct": is_correct,
        "score": score,
        "max_score": max_score,
        "step_results": step_results,
        "error_types": list(ea["error_types"]),
        "ai_confidence": ea["confidence"],
        "overall_feedback": ea["overall_feedback"],
        "need_teacher_review": ea.get("need_teacher_review", False),
    }


class MockProvider(LLMProvider):
    """Rule-engine-backed provider. Zero network, zero external deps.

    The provider is stateless - every call to ``grade_step`` and
    friends reads the relevant JSON file fresh through
    ``engine.grader.load_json``. (The leader is concurrently
    working on a ``load_json`` cache; once that lands, the cache
    is automatically picked up because we delegate to the same
    module functions.)
    """

    @property
    def name(self) -> str:
        """Stable identifier used as the ``model`` field in trace records."""
        return "mock"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def grade_step(
        self,
        *,
        question: Dict[str, Any],
        student_answer: str,
        standard_answer: str,
        student_id: str,
        trace: Optional[TraceCollector] = None,
    ) -> Dict[str, Any]:
        """Delegate to ``engine.grader.grade_long_answer`` and record trace.

        ``standard_answer`` is accepted for API symmetry with the real
        provider but ignored here - the rule engine reads
        ``question["answer"]`` directly.

        Sprint 2: when ``question.subject_type`` is set and is not
        ``math_calculation``, use the multi-subject mock fixtures to
        return a structured result matching that subject's expected
        analysis shape. This lets the full chain be tested in mock
        mode for all 7 subjects without a real LLM key.
        """
        # Local import keeps the engine.llm package importable in
        # environments where the wider engine is not on the path
        # (e.g. unit tests run from the demo/ directory).
        from engine import grader

        started = time.time()

        # Sprint 2: multi-subject mock dispatch
        subject_type = question.get("subject_type")
        result = None
        if subject_type and subject_type != "math_calculation":
            result = _mock_multi_subject_grade(question, student_answer, student_id)

        if result is None:
            result = grader.grade_long_answer(student_answer, question, student_id)

        duration_ms = round((time.time() - started) * 1000.0, 2)

        if trace is not None:
            trace.record(
                stage="math_grading",
                input_payload={
                    "question_id": question.get("id"),
                    "student_id": pseudonymize_student_id(student_id),
                    "student_answer_length": len(student_answer or ""),
                    "expected_answer_length": len(standard_answer or ""),
                    "subject_type": subject_type or "math_calculation",
                },
                output_payload={
                    "is_correct": result.get("is_correct"),
                    "score": result.get("score"),
                    "error_types": result.get("error_types", []),
                    "ai_confidence": result.get("ai_confidence"),
                    "need_teacher_review": result.get("need_teacher_review"),
                    "step_count": len(result.get("step_results", [])),
                },
                duration_ms=duration_ms,
                confidence=float(result.get("ai_confidence", 0.0) or 0.0),
                model=self.name,
            )
        return result

    def validate_correction(
        self,
        *,
        question: Dict[str, Any],
        student_correction: str,
        expected_answer: str,
        trace: Optional[TraceCollector] = None,
    ) -> Dict[str, Any]:
        """Delegate to ``engine.grader.verify_correction`` and record trace.

        Note: the legacy rule engine path is preserved as a
        transparent fallback so the demo continues to work even
        when this method is called without an LLM.
        """
        from engine import grader

        started = time.time()
        result = grader.verify_correction(
            question_id=question.get("id", ""),
            student_id="",  # mock path doesn't use student_id
            correction_text=student_correction,
        )
        duration_ms = round((time.time() - started) * 1000.0, 2)

        if trace is not None:
            trace.record(
                stage="correction_validation",
                input_payload={
                    "question_id": question.get("id"),
                    "student_correction_length": len(student_correction or ""),
                },
                output_payload={
                    "is_correct": result.get("is_correct"),
                    "loop_closed": result.get("loop_closed"),
                },
                duration_ms=duration_ms,
                confidence=0.6 if result.get("is_correct") else 0.4,
                model=self.name,
            )
        return result

    def generate_comment(
        self,
        *,
        student: Dict[str, Any],
        performance: Dict[str, Any],
        trace: Optional[TraceCollector] = None,
    ) -> str:
        """Delegate to ``engine.grader.generate_personalized_comment``.

        ``performance`` must include at least ``assignment_id`` so
        the rule engine can locate the answers/questions JSONs.
        """
        from engine import grader

        started = time.time()
        comment = grader.generate_personalized_comment(
            student_id=student.get("id", ""),
            assignment_id=performance.get("assignment_id", "hw_001"),
        )
        duration_ms = round((time.time() - started) * 1000.0, 2)

        if trace is not None:
            trace.record(
                stage="comment_generation",
                input_payload={
                    "student_id": pseudonymize_student_id(student.get("id", "")),
                    "assignment_id": performance.get("assignment_id"),
                    "performance_keys": sorted(performance.keys()),
                },
                output_payload={
                    "comment_length": len(comment or ""),
                    "comment_preview": (comment or "")[:60],
                },
                duration_ms=duration_ms,
                confidence=0.7,  # mock: medium confidence
                model=self.name,
            )
        return comment
