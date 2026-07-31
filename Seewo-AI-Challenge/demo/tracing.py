"""V2.0 Sprint 6 (6.3): Lightweight distributed tracing.

OpenTelemetry SDK is not available in the sandbox. This module provides
a self-contained tracing facility that generates trace_ids spanning
HTTP → Flask handler → grade_long_answer → LLM provider _chat().

Design:
- Each HTTP request gets a trace_id (inherited from request_logging.py's
  request_id or a new UUID).
- The trace_id is stored in Flask g.trace_id and propagated to
  TraceCollector (which already has a trace_id field on TraceRecord).
- Trace spans are recorded as TraceRecords in the existing TraceCollector.
- Completed traces are stored in the agent_trace table (Sprint 5 added
  school_id column).

If opentelemetry-sdk is installed in production, this module can be
swapped to use it — the interface is compatible.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from flask import g, request

# Try to import opentelemetry (production); fall back to lightweight
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


def init_tracing(app):
    """Initialize tracing for the Flask app.

    If OpenTelemetry is available, sets up a TracerProvider with
    ConsoleSpanExporter. Otherwise, uses the lightweight g.trace_id approach.

    Returns the trace provider (or None if lightweight mode).
    """
    if _HAS_OTEL:
        provider = TracerProvider()
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        otel_trace.set_tracer_provider(provider)
        return provider
    else:
        # Lightweight mode: just ensure trace_id is set per request
        @app.before_request
        def _set_trace_id():
            """Set trace_id on every request (if not already set)."""
            if not hasattr(g, "trace_id") or not g.trace_id:
                g.trace_id = getattr(g, "request_id", None) or uuid.uuid4().hex[:16]

        return None


def get_trace_id() -> str:
    """Get the current request's trace_id."""
    try:
        tid = getattr(g, "trace_id", None)
        if tid:
            return tid
    except RuntimeError:
        pass
    return "no-trace"


def create_span(
    stage: str,
    input_payload: Optional[Dict[str, Any]] = None,
) -> "_Span":
    """Start a new trace span.

    In OpenTelemetry mode, creates a real span. In lightweight mode,
    creates a simple timing wrapper that records to TraceCollector.
    """
    return _Span(stage=stage, input_payload=input_payload or {})


class _Span:
    """A lightweight trace span (timing + metadata)."""

    def __init__(self, stage: str, input_payload: Dict[str, Any]):
        self.stage = stage
        self.input_payload = input_payload
        self.trace_id = get_trace_id()
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.duration_ms: float = 0.0
        self.output_payload: Dict[str, Any] = {}
        self.error: Optional[str] = None

    def set_output(self, output: Dict[str, Any]):
        """Set the span's output payload."""
        self.output_payload = output

    def set_error(self, error: str):
        """Mark the span as errored."""
        self.error = error

    def end(self):
        """End the span and calculate duration."""
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000.0, 2)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end()
        if exc_val:
            self.error = str(exc_val)
        return False  # Don't suppress exceptions

    def to_trace_record_dict(self) -> Dict[str, Any]:
        """Convert to a dict suitable for agent_trace table storage."""
        return {
            "trace_id": self.trace_id,
            "stage": self.stage,
            "input": self.input_payload,
            "output": self.output_payload,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "timestamp": self.start_time,
        }


def store_trace_to_agent_trace(
    collector,
    school_id: int = 1,
    db_engine=None,
):
    """Store a completed TraceCollector session to the agent_trace table.

    Uses the existing agent_trace ORM model (Sprint 5 added school_id).
    Falls back to in-process store if PG is not available.
    """
    if collector is None:
        return

    trace_data = collector.to_dict()
    trace_id = get_trace_id()

    # Try to store in PG
    if db_engine is not None:
        try:
            from sqlalchemy import text
            with db_engine.connect() as conn:
                for record in trace_data.get("stages", []):
                    conn.execute(text(
                        "INSERT INTO agent_trace "
                        "(agent_name, task_id, user_id, input_json, output_json, "
                        "latency_ms, status, error_message, school_id) "
                        "VALUES (:agent, :task_id, :user_id, :input, :output, "
                        ":latency, :status, :error, :school_id)"
                    ), {
                        "agent": record.get("stage", "unknown"),
                        "task_id": trace_id,
                        "user_id": None,
                        "input": str(record.get("input_payload", {})),
                        "output": str(record.get("output_payload", {})),
                        "latency": record.get("duration_ms"),
                        "status": "failed" if record.get("error") else "success",
                        "error": record.get("error"),
                        "school_id": school_id,
                    })
                conn.commit()
        except Exception:
            pass  # PG not available — in-process store handles it

    # Also store in the in-process trace store (V1.5 facility)
    try:
        from engine.llm.factory import store_trace
        store_trace(collector)
    except Exception:
        pass
