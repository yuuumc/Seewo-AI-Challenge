"""Provider factory + in-process trace store.

This module is the single point of contact between the rest of the
engine and the LLM provider layer. It exposes:

    get_provider()             - lazy singleton, mock or real per env
    get_runtime_trace(...)     - drop-in replacement for the pre-baked
                                 ``engine.grader.get_agent_trace`` route
    reset_runtime_trace_store  - test helper

The trace store is intentionally in-process and bounded. It keeps
the last N trace collectors per ``(student_id, assignment_id)``
key so that:

    * multiple sequential requests for the same student don't
      overwrite each other (N=8 covers all the demo's pages);
    * the store does not grow unbounded in a long-running demo
      (a leak guard - the previous behaviour was a static JSON
      file, which had the same property implicitly).
"""
from __future__ import annotations

import os
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from engine.llm.base import LLMProvider, TraceCollector


# Maximum number of historical trace collectors to retain per
# (student_id, assignment_id) key. Once exceeded, the oldest entry
# is evicted in FIFO order. Sized to match the maximum number of
# requests a single demo page can produce.
_MAX_TRACES_PER_KEY = 8

# In-process trace store: ``[(student_id, assignment_id)] -> [TraceCollector]``
_RUNTIME_TRACE_STORE: "OrderedDict[Tuple[str, str], List[TraceCollector]]" = OrderedDict()
_STORE_LOCK = Lock()

# Singleton provider cache. We keep the provider and a tuple of
# the env-var values it was selected against; a mismatch forces
# a re-resolve. Using a tuple (not ``hash()``) makes the test
# behaviour predictable and avoids the salt-randomisation of
# ``hash(str)`` between Python processes.
_PROVIDER: Optional[LLMProvider] = None
_PROVIDER_ENV_FINGERPRINT: Optional[Tuple[str, str, str]] = None
_PROVIDER_LOCK = Lock()


def _env_fingerprint() -> Tuple[str, str, str]:
    """Return the env-var tuple that drives provider selection.

    Stable across processes (unlike ``hash()`` of strings, which
    is salted per-process) so tests can rely on it.
    """
    return (
        os.environ.get("LLM_API_KEY", "").strip(),
        os.environ.get("LLM_BASE_URL", "").strip(),
        os.environ.get("LLM_MODEL", "").strip(),
    )


def get_provider() -> LLMProvider:
    """Return a process-wide singleton :class:`LLMProvider`.

    Selection rule:

        1. If ``LLM_API_KEY`` is non-empty -> :class:`OpenAIProvider`
           (default OpenAI-compatible endpoint) OR
           :class:`DeepSeekProvider` (when ``LLM_MODEL=deepseek-math``)
        2. Otherwise                       -> :class:`MockProvider`

    C-08 DeepSeek-Math dispatch: triggered solely by
    ``LLM_MODEL == "deepseek-math"`` (case-insensitive). Every other
    value falls through to the original OpenAI path — default
    behaviour is unchanged for unset / non-deepseek LLM_MODEL.

    The singleton is invalidated whenever any of the three
    env vars change. This makes the function safe to call in
    tests that mutate ``os.environ`` (and cheap enough to call
    on every request - it's just three ``os.environ.get`` calls).
    """
    global _PROVIDER, _PROVIDER_ENV_FINGERPRINT

    fp = _env_fingerprint()
    with _PROVIDER_LOCK:
        if _PROVIDER is not None and _PROVIDER_ENV_FINGERPRINT == fp:
            return _PROVIDER
        # Import locally to avoid a circular import at package load.
        from engine.llm.openai_provider import read_provider_config_from_env
        from engine.llm.openai_provider import OpenAIProvider
        from engine.llm.mock_provider import MockProvider

        cfg = read_provider_config_from_env()
        if cfg is None:
            _PROVIDER = MockProvider()
        elif cfg["model"].strip().lower() == "deepseek-math":
            # C-08: dedicated DeepSeek-Math provider. Single env-only
            # config source (no second Pydantic layer); default base_url
            # is the DeepSeek official endpoint (LLM_BASE_URL overrides).
            from engine.llm.deepseek_provider import (
                DeepSeekProvider,
                read_deepseek_config_from_env,
            )

            _PROVIDER = DeepSeekProvider(**read_deepseek_config_from_env())
        else:
            _PROVIDER = OpenAIProvider(
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                model=cfg["model"],
                timeout=float(cfg["timeout"]),
                max_retries=int(cfg["max_retries"]),
            )
        _PROVIDER_ENV_FINGERPRINT = fp
        return _PROVIDER


def store_trace(collector: TraceCollector) -> None:
    """Register a :class:`TraceCollector` in the in-process store.

    Called by the integration patch inside ``grade_long_answer``
    once the collector has been populated. Thread-safe; bounded
    to ``_MAX_TRACES_PER_KEY`` entries per key.
    """
    key = (collector.student_id, collector.assignment_id)
    with _STORE_LOCK:
        bucket = _RUNTIME_TRACE_STORE.setdefault(key, [])
        bucket.append(collector)
        # Evict oldest if over capacity.
        while len(bucket) > _MAX_TRACES_PER_KEY:
            bucket.pop(0)
        # Move key to the end so the store reflects recency.
        _RUNTIME_TRACE_STORE.move_to_end(key)


def get_runtime_trace(
    student_id: str,
    assignment_id: str,
) -> Dict[str, Any]:
    """Return the most recent runtime trace for the given key.

    The return shape mirrors ``engine.grader.get_agent_trace`` for
    drop-in compatibility: ``{"agents": [...], "trace": str, ...}``.
    When no collector exists for the key, the pre-baked JSON from
    the legacy ``agent_traces.json`` is returned as a graceful
    fallback (so the original demo still works for users who never
    trigger a real grading request).
    """
    key = (student_id, assignment_id)
    with _STORE_LOCK:
        bucket = _RUNTIME_TRACE_STORE.get(key, [])

    if bucket:
        latest = bucket[-1]
        d = latest.to_dict()
        # Synthesise the legacy ``agents`` / ``trace`` string for
        # templates that haven't been migrated yet.
        d["agents"] = list({r.stage for r in latest.records})
        d["trace"] = " → ".join(
            f"{r.stage}({r.duration_ms:.0f}ms)" for r in latest.records
        )
        d["review_needed"] = any(
            (r.error or r.confidence < 0.7) for r in latest.records
        )
        return d

    # Graceful fallback: the pre-baked JSON. This preserves demo
    # behaviour for users who load the agent-trace page without
    # first triggering a grading flow.
    try:
        from engine.grader import load_json
        traces = load_json("agent_traces.json")
        return traces.get(
            f"{student_id}_{assignment_id}",
            {"agents": [], "trace": "未找到追踪数据", "review_needed": False},
        )
    except Exception:  # pragma: no cover - defensive
        return {"agents": [], "trace": "未找到追踪数据", "review_needed": False}


def reset_runtime_trace_store() -> None:
    """Clear all stored traces + reset the provider singleton.

    Test helper. Idempotent.
    """
    with _STORE_LOCK:
        _RUNTIME_TRACE_STORE.clear()
    global _PROVIDER, _PROVIDER_ENV_FINGERPRINT
    with _PROVIDER_LOCK:
        _PROVIDER = None
        _PROVIDER_ENV_FINGERPRINT = None
