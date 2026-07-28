"""LLM provider abstraction for Seewo-AI-Challenge.

This package introduces a pluggable LLM provider layer that wraps
the existing rule-based mock engine and adds a real-LLM path. The
factory auto-selects based on environment variables so the demo
remains fully functional without any LLM credentials.

Public API (used by the integration patches in PATCHES.md):

    from engine.llm import get_provider, TraceCollector, get_runtime_trace

    provider = get_provider()           # mock or openai based on env
    trace = TraceCollector(student_id, assignment_id)
    result = provider.grade_step(
        question=q, student_answer=sa, standard_answer=std, trace=trace,
    )
    comment = provider.generate_comment(student=stu, performance=perf, trace=trace)
    trace_records = get_runtime_trace(student_id, assignment_id)

Environment variables:
    LLM_API_KEY    - if set and non-empty, real provider is selected
    LLM_BASE_URL   - OpenAI-compatible base URL (default: https://api.openai.com/v1)
    LLM_MODEL      - model name (default: gpt-4o-mini)
    LLM_TIMEOUT    - request timeout in seconds (default: 30)
    LLM_MAX_RETRIES - max retry attempts on transient failure (default: 1)

The package has zero external dependencies beyond the Python standard
library (urllib for HTTP). This is by design so the demo continues to
boot with `pip install flask` only.
"""
from __future__ import annotations

from engine.llm.base import (
    LLMProvider,
    TraceRecord,
    TraceCollector,
)
from engine.llm.factory import (
    get_provider,
    get_runtime_trace,
    reset_runtime_trace_store,
    store_trace,
)

__all__ = [
    "LLMProvider",
    "TraceRecord",
    "TraceCollector",
    "get_provider",
    "get_runtime_trace",
    "reset_runtime_trace_store",
    "store_trace",
]
