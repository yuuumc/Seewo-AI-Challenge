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

# Per-school provider cache (Sprint 6 · 6.7). Keyed by school_id so
# that different tenants can have different LLM configs. Each entry
# stores the provider and a fingerprint tuple of the config values
# it was built against; a mismatch forces re-resolve.
_PROVIDERS: Dict[int, LLMProvider] = {}
_PROVIDER_FINGERPRINTS: Dict[int, tuple] = {}
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


def _resolve_fingerprint(school_id: int) -> tuple:
    """Return config fingerprint for a school: env vars + tenant config.

    Includes tenant-level overrides so that a config change for a
    specific school invalidates only that school's cached provider.
    """
    env_fp = _env_fingerprint()
    try:
        from tenant_llm_config_manager import get_tenant_config

        tenant = get_tenant_config(school_id)
        if tenant:
            tenant_fp = (
                str(tenant.get("model_name")),
                str(tenant.get("base_url")),
                str(tenant.get("api_key_secret")),
                str(tenant.get("temperature")),
                str(tenant.get("timeout")),
            )
            return env_fp + tenant_fp
    except Exception:
        pass
    return env_fp


def _build_provider(school_id: int) -> LLMProvider:
    """Construct a provider for the given school.

    Resolution order (Sprint 6 · 6.7):
        1. Tenant config (tenant_llm_config_manager.resolve_llm_config)
        2. Environment variables (read_provider_config_from_env)
        3. MockProvider (fallback when no API key anywhere)
    """
    from engine.llm.openai_provider import (
        read_provider_config_from_env,
        OpenAIProvider,
    )
    from engine.llm.mock_provider import MockProvider

    # Try tenant config first
    cfg = None
    try:
        from tenant_llm_config_manager import resolve_llm_config

        resolved = resolve_llm_config(school_id)
        if resolved.get("api_key"):
            # Normalize tenant config keys to provider constructor keys
            cfg = {
                "base_url": resolved.get("base_url", ""),
                "api_key": resolved.get("api_key", ""),
                "model": resolved.get("model_name", ""),
                "timeout": str(resolved.get("timeout", 30)),
                "max_retries": os.environ.get("LLM_MAX_RETRIES", "1").strip(),
            }
            # Validate allowlist for tenant overrides
            from engine.llm.allowlist import safe_validate

            if not safe_validate(
                cfg["base_url"], cfg["model"], provider_name="openai"
            ):
                cfg = None  # fail-safe → fall through to env / mock
    except Exception:
        pass

    if cfg is None:
        cfg = read_provider_config_from_env()

    if cfg is None:
        return MockProvider()

    model_lower = cfg["model"].strip().lower()
    if model_lower == "deepseek-math":
        from engine.llm.deepseek_provider import (
            DeepSeekProvider,
            read_deepseek_config_from_env,
        )

        try:
            return DeepSeekProvider(**read_deepseek_config_from_env())
        except ValueError:
            return MockProvider()

    return OpenAIProvider(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        timeout=float(cfg["timeout"]),
        max_retries=int(cfg["max_retries"]),
    )


def get_provider(school_id: int = 1) -> LLMProvider:
    """Return a per-school singleton :class:`LLMProvider`.

    Sprint 6 (6.7): now accepts ``school_id`` to support multi-tenant
    LLM configs. Each school gets its own cached provider, built from
    tenant config overrides (if any) or env vars. Backward compatible:
    ``get_provider()`` with no args uses ``school_id=1`` (the default
    school), preserving pre-V2.0 behaviour.

    The singleton for a given school is invalidated whenever the env
    vars or that school's tenant config change.
    """
    fp = _resolve_fingerprint(school_id)
    with _PROVIDER_LOCK:
        if school_id in _PROVIDERS and _PROVIDER_FINGERPRINTS.get(school_id) == fp:
            return _PROVIDERS[school_id]
        _PROVIDERS[school_id] = _build_provider(school_id)
        _PROVIDER_FINGERPRINTS[school_id] = fp
        return _PROVIDERS[school_id]


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
    """Clear all stored traces + reset all cached providers.

    Test helper. Idempotent.
    """
    with _STORE_LOCK:
        _RUNTIME_TRACE_STORE.clear()
    with _PROVIDER_LOCK:
        _PROVIDERS.clear()
        _PROVIDER_FINGERPRINTS.clear()
