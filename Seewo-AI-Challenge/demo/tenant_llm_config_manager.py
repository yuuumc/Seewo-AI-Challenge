"""V2.0 Sprint 6 (6.7): 多租户 LLM 配置管理.

配置层级（优先级从低到高）:
  1. 全局默认（环境变量 LLM_MODEL / LLM_TEMPERATURE / ...）
  2. 租户覆盖（tenant_llm_config 表，school_id 为 PK）
  3. 学科 overlay（tenant_llm_config.subject_overrides JSONB，NULL 继承）

数据存储:
  - JSON 模式: data/tenant_llm_config.json
  - PG 模式: tenant_llm_config 表（Alembic 0005）

API:
  resolve_llm_config(school_id, subject_type) → dict
  get_tenant_config(school_id) → dict | None
  set_tenant_config(school_id, **kwargs) → dict
  delete_tenant_config(school_id) → bool
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from security import audit_log, get_current_user

_DATA_DIR = Path(__file__).parent / "data"
_CONFIG_FILE = _DATA_DIR / "tenant_llm_config.json"

# Global defaults from environment
_GLOBAL_DEFAULTS = {
    "model_name": lambda: os.environ.get("LLM_MODEL", "deepseek-chat"),
    "temperature": lambda: float(os.environ.get("LLM_TEMPERATURE", "0.2")),
    "max_tokens": lambda: int(os.environ.get("LLM_MAX_TOKENS", "4096")),
    "timeout": lambda: float(os.environ.get("LLM_TIMEOUT", "30")),
    "api_key": lambda: os.environ.get("LLM_API_KEY", ""),
    "base_url": lambda: os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
}


def _global_defaults() -> dict:
    """Return current global default config from environment."""
    return {k: fn() for k, fn in _GLOBAL_DEFAULTS.items()}


def _load_all() -> list[dict]:
    if not _CONFIG_FILE.exists():
        return []
    with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_all(configs: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)
    tmp.replace(_CONFIG_FILE)


def get_tenant_config(school_id: int) -> Optional[dict]:
    """Get tenant LLM config for a school. Returns None if not configured."""
    configs = _load_all()
    for c in configs:
        if c.get("school_id") == school_id:
            return c
    return None


def resolve_llm_config(school_id: int = 1, subject_type: str | None = None) -> dict:
    """Resolve effective LLM config: global ← tenant ← subject overlay.

    Args:
        school_id: school ID (default 1)
        subject_type: optional subject key for overlay (e.g. "math_step_grading")

    Returns:
        dict with keys: model_name, temperature, max_tokens, timeout, api_key, base_url
    """
    # Layer 1: global defaults
    cfg = _global_defaults()

    # Layer 2: tenant override
    tenant = get_tenant_config(school_id)
    if tenant:
        for k in ("model_name", "temperature", "max_tokens", "timeout", "base_url"):
            v = tenant.get(k)
            if v is not None:
                cfg[k] = v
        # api_key_secret: decrypt if present (simplified: plaintext in JSON for demo)
        if tenant.get("api_key_secret"):
            cfg["api_key"] = tenant["api_key_secret"]

        # Layer 3: subject overlay
        if subject_type and tenant.get("subject_overrides"):
            overrides = tenant["subject_overrides"]
            ov = overrides.get(subject_type, {})
            for k, v in ov.items():
                if k in cfg and v is not None:
                    cfg[k] = v

    cfg["school_id"] = school_id
    return cfg


def set_tenant_config(school_id: int, **kwargs) -> dict:
    """Create or update tenant LLM config. Returns the stored config.

    Only non-None values are written (NULL = inherit global).
    """
    configs = _load_all()
    existing = None
    for c in configs:
        if c.get("school_id") == school_id:
            existing = c
            break

    if existing:
        # Update: only set non-None values
        action = "update"
        changed_fields = []
        for k, v in kwargs.items():
            if v is not None and existing.get(k) != v:
                old_val = existing.get(k)
                # Mask api_key in audit
                old_display = "***" if k == "api_key_secret" and old_val else str(old_val)
                new_display = "***" if k == "api_key_secret" and v else str(v)
                changed_fields.append({
                    "field": k,
                    "old": old_display,
                    "new": new_display,
                })
                existing[k] = v
        config = existing
    else:
        action = "create"
        config = {
            "school_id": school_id,
            "model_name": kwargs.get("model_name"),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
            "timeout": kwargs.get("timeout"),
            "api_key_secret": kwargs.get("api_key_secret"),
            "base_url": kwargs.get("base_url"),
            "subject_overrides": kwargs.get("subject_overrides", {}),
            "updated_by": "",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        }
        configs.append(config)

    config["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    user = get_current_user()
    config["updated_by"] = user.get("user_id", "system") if user else "system"

    _save_all(configs)

    audit_log(
        "tenant_llm_config_change",
        school_id=school_id,
        action=action,
        changed_by=config["updated_by"],
        resource=f"tenant_llm_config:{school_id}",
    )
    return config


def delete_tenant_config(school_id: int) -> bool:
    """Delete tenant LLM config. School falls back to global defaults."""
    configs = _load_all()
    new_configs = [c for c in configs if c.get("school_id") != school_id]
    if len(new_configs) == len(configs):
        return False

    _save_all(new_configs)
    audit_log(
        "tenant_llm_config_change",
        school_id=school_id,
        action="delete",
        resource=f"tenant_llm_config:{school_id}",
    )
    return True


def list_tenant_configs() -> list[dict]:
    """List all tenant configs (for admin UI)."""
    return _load_all()
