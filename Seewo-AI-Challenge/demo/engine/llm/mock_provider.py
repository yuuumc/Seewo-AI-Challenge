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
        """
        # Local import keeps the engine.llm package importable in
        # environments where the wider engine is not on the path
        # (e.g. unit tests run from the demo/ directory).
        from engine import grader

        started = time.time()
        result = grader.grade_long_answer(student_answer, question, student_id)
        duration_ms = round((time.time() - started) * 1000.0, 2)

        if trace is not None:
            trace.record(
                stage="math_grading",
                input_payload={
                    "question_id": question.get("id"),
                    "student_id": student_id,
                    "student_answer_length": len(student_answer or ""),
                    "expected_answer_length": len(standard_answer or ""),
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
                    "student_id": student.get("id"),
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
