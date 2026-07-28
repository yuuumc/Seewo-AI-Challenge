"""Abstract base class for LLM providers + shared data types.

The provider abstraction covers the three primary AI capabilities the
homework grading engine needs:

    1. ``grade_step``        - step-level analysis of a long-answer question
    2. ``validate_correction`` - decide whether a student's correction is acceptable
    3. ``generate_comment``    - produce a warm, personalized feedback comment

Every provider is expected to (a) be import-safe with no network
calls and (b) expose a ``name`` property that is used as the
``model`` field in :class:`TraceRecord` so we can tell mock vs
real-LLM runs apart in the trace.

A :class:`TraceCollector` is threaded through every call. Providers
MUST record exactly one :class:`TraceRecord` per invocation,
including the case where they short-circuit to a fallback (so the
operator can see *why* a real-LLM path was abandoned).
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TraceRecord:
    """One stage of the multi-agent grading pipeline.

    Fields
    ------
    stage:
        Logical stage name. Recommended values follow the
        ``MathPilot`` Agent taxonomy declared in
        ``05_技术方案.md`` §2.2: ``ocr`` / ``math_grading`` /
        ``knowledge_graph`` / ``diagnosis`` / ``teaching_strategy`` /
        ``correction_validation`` / ``comment_generation`` /
        ``fallback``.
    input_payload:
        Provider-specific input snapshot. Keep it small and
        JSON-serialisable (avoid raw image bytes).
    output_payload:
        Provider-specific output snapshot. Same constraints as
        ``input_payload``.
    duration_ms:
        Wall-clock duration of the call in milliseconds.
    confidence:
        0.0-1.0. The mock provider reports the rule-engine
        ``ai_confidence`` verbatim. Real providers should report
        ``None`` or the LLM's stated confidence.
    timestamp:
        Unix epoch seconds (float).
    error:
        ``None`` on success, otherwise a short human-readable string.
    model:
        ``"mock"`` for the rule engine, otherwise the LLM model name
        as reported by the provider's :pyattr:`LLMProvider.name`.
    """
    stage: str
    input_payload: Dict[str, Any]
    output_payload: Dict[str, Any]
    duration_ms: float
    confidence: float
    timestamp: float
    model: str
    error: Optional[str] = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict (recursively)."""
        return asdict(self)


class TraceCollector:
    """Per-grading-session accumulator for :class:`TraceRecord`.

    The collector is the runtime replacement for the pre-baked
    ``data/agent_traces.json`` that the original demo shipped with.
    Every provider call that goes through the engine MUST thread the
    same collector instance, so the records form an end-to-end
    timeline of the multi-agent collaboration.

    A global registry (``engine.llm.factory._RUNTIME_TRACE_STORE``)
    keeps the last N collectors per ``(student_id, assignment_id)``
    so the existing ``get_agent_trace`` route can be replaced by
    :func:`engine.llm.factory.get_runtime_trace` without a database.
    """

    def __init__(self, student_id: str, assignment_id: str) -> None:
        self.student_id = student_id
        self.assignment_id = assignment_id
        self.started_at: float = time.time()
        self.records: List[TraceRecord] = []

    # ------------------------------------------------------------------
    # Recording API
    # ------------------------------------------------------------------
    def record(
        self,
        stage: str,
        input_payload: Dict[str, Any],
        output_payload: Dict[str, Any],
        duration_ms: float,
        confidence: float,
        model: str,
        error: Optional[str] = None,
    ) -> TraceRecord:
        """Append a new :class:`TraceRecord` to this session.

        Parameters mirror :class:`TraceRecord` minus ``timestamp``
        (auto-stamped) and ``trace_id`` (auto-generated).
        """
        rec = TraceRecord(
            stage=stage,
            input_payload=input_payload,
            output_payload=output_payload,
            duration_ms=duration_ms,
            confidence=confidence,
            timestamp=time.time(),
            model=model,
            error=error,
        )
        self.records.append(rec)
        return rec

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the entire session trace to a JSON-safe dict.

        The schema intentionally mirrors the data shape that
        ``teacher_agent_trace.html`` already renders, so the
        existing template can keep working once the integration
        patch swaps the data source.
        """
        return {
            "student_id": self.student_id,
            "assignment_id": self.assignment_id,
            "started_at": self.started_at,
            "duration_ms_total": round(
                (time.time() - self.started_at) * 1000.0, 2
            ),
            "stages": [r.to_dict() for r in self.records],
            "stage_count": len(self.records),
            "errors": [r.to_dict() for r in self.records if r.error],
        }


class LLMProvider(ABC):
    """Abstract LLM provider.

    All three methods are coroutine-style pure functions: same input
    → same output (modulo the LLM's own non-determinism). They take
    a :class:`TraceCollector` and MUST record exactly one
    :class:`TraceRecord` per call, including when they delegate or
    fall back. This is the contract that makes the
    ``engine.llm.factory.get_runtime_trace`` view useful.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used as ``model`` field in trace records.

        The mock provider returns ``"mock"``; the OpenAI-compatible
        provider returns the configured model name.
        """
        raise NotImplementedError

    @abstractmethod
    def grade_step(
        self,
        *,
        question: Dict[str, Any],
        student_answer: str,
        standard_answer: str,
        student_id: str,
        trace: Optional[TraceCollector] = None,
    ) -> Dict[str, Any]:
        """Step-level grading for a single long-answer question.

        The returned dict MUST be shape-compatible with the existing
        ``engine.grader.grade_long_answer`` return value so the
        downstream HTML templates keep rendering. Concretely it
        must contain: ``type``, ``student_answer``, ``correct_answer``,
        ``is_correct``, ``score``, ``max_score``, ``step_results``,
        ``error_types``, ``ai_confidence``, ``overall_feedback``,
        ``need_teacher_review``.

        Parameters
        ----------
        question:
            The question dict as it appears in ``data/questions.json``,
            including ``id``, ``type``, ``stem``, ``score``,
            ``answer`` and ``steps``.
        student_answer:
            Raw student answer text (post-OCR in real systems;
            already-extracted in mock mode).
        standard_answer:
            The expected answer string (``question["answer"]``).
        student_id:
            e.g. ``"s02"``. Used to disambiguate per-student mock
            patterns.
        trace:
            Optional collector. If provided, the provider records
            its execution here. If ``None``, the provider should
            skip recording (used by the smoke tests).
        """
        raise NotImplementedError

    @abstractmethod
    def validate_correction(
        self,
        *,
        question: Dict[str, Any],
        student_correction: str,
        expected_answer: str,
        trace: Optional[TraceCollector] = None,
    ) -> Dict[str, Any]:
        """Decide whether a student's correction is acceptable.

        The returned dict MUST be shape-compatible with the existing
        ``engine.grader.verify_correction`` return value. Concretely
        it must contain: ``is_correct`` (bool), ``feedback`` (str),
        ``verified_by_ai`` (bool), ``loop_closed`` (bool).

        The mock provider falls back to the legacy
        ``"f'(x)" in text and "单调" in text`` heuristic so the demo
        continues to work. The real provider does semantic
        comparison via the LLM.
        """
        raise NotImplementedError

    @abstractmethod
    def generate_comment(
        self,
        *,
        student: Dict[str, Any],
        performance: Dict[str, Any],
        trace: Optional[TraceCollector] = None,
    ) -> str:
        """Produce a warm, personalized comment for the student.

        ``student`` carries ``id`` and ``name``. ``performance``
        carries the same fields as
        ``engine.grader.generate_personalized_comment`` consumes
        (``total``, ``max_score``, ``mistakes``, etc.).

        The returned string is rendered directly into the
        ``teacher_grade.html`` template; keep it short (one
        sentence each for opening and closing).
        """
        raise NotImplementedError
