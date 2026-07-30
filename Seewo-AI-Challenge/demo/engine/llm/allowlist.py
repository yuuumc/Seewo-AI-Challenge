"""LLM provider host + model allowlist (SSRF guard).

V1.0 Sprint 1 — 工程配套 item 5: 限制 LLM provider 的 base_url 主机和
model 名称可选范围，防止通过环境变量注入内网地址（SSRF）或任意模型。

设计要点
--------
* **IP 字面量硬门**：``LLM_BASE_URL`` 的 host 若为保留 / 私网 IP 字面量
  （``169.254.169.254`` 云元数据、``127.x``、``10.x``、``172.16-31.x``、
  ``192.168.x``、``0.0.0.0`` 等），**始终拒绝** —— SSRF 核心向量。
* **Hostname 白名单（opt-in）**：仅当 ``ALLOWED_LLM_HOSTS`` 环境变量设置时
  启用主机名白名单；未设置时允许任意非保留-IP 的 hostname（支持私有 LLM
  部署）。生产环境显式设置以收紧。
* ``LLM_MODEL`` 必须匹配某个允许的前缀（``gpt-`` / ``deepseek-`` 等），
  可通过 ``ALLOWED_LLM_MODEL_PREFIXES`` 扩展。
* 不做 DNS 解析后 IP 检查 —— 沙箱 / CI DNS 劫持公网域名到本地 IP 会误杀
  合法主机，且 hostname→IP 的 DNS rebinding 攻击面远小于直接 IP 注入。
* 校验失败时 ``safe_validate`` 返回 ``False``；调用方
  （``read_*_config_from_env``）据此回退到 MockProvider（fail-safe）。
"""
from __future__ import annotations

import ipaddress
import logging
import os
from typing import FrozenSet
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── 默认白名单 ──────────────────────────────────────────────────────
_DEFAULT_ALLOWED_HOSTS: FrozenSet[str] = frozenset(
    {
        "api.openai.com",
        "api.deepseek.com",
    }
)

_DEFAULT_ALLOWED_MODEL_PREFIXES: FrozenSet[str] = frozenset(
    {
        "gpt-",
        "gpt4",
        "o1-",
        "o1",
        "o3-",
        "o3",
        "o4-",
        "o4",
        "deepseek-",
        "deepseek/",
    }
)

# 私网 / 保留 IP 前缀（is_private 已覆盖，这里显式列出便于审计）
_RESERVED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / 云元数据
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _allowed_hosts() -> FrozenSet[str]:
    """Hostname 白名单（opt-in）：仅返回 ``ALLOWED_LLM_HOSTS`` 环境变量提供的主机。

    未设置时返回空集 → hostname 白名单不启用（允许任意非保留-IP 的 hostname，
    支持私有 LLM 部署）。生产环境显式设置 ``ALLOWED_LLM_HOSTS`` 以收紧。
    """
    extra = os.environ.get("ALLOWED_LLM_HOSTS", "")
    return frozenset(h.strip().lower() for h in extra.split(",") if h.strip())


def _allowed_model_prefixes() -> FrozenSet[str]:
    """默认模型前缀白名单 + 环境变量追加项（小写化、去空）。"""
    extra = os.environ.get("ALLOWED_LLM_MODEL_PREFIXES", "")
    extra_set = frozenset(
        p.strip().lower() for p in extra.split(",") if p.strip()
    )
    return _DEFAULT_ALLOWED_MODEL_PREFIXES | extra_set


def _is_reserved_ip(ip_str: str) -> bool:
    """判断 IP 是否落在保留 / 私网段。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    return any(ip in net for net in _RESERVED_NETWORKS)


def validate_llm_base_url(base_url: str) -> str:
    """校验 LLM base_url，防止 SSRF。

    策略（两层）：
    1. **IP 字面量硬门**：若 host 是 IP 字面量且落在保留 / 私网段
       （169.254.x 云元数据、127.x、10.x、172.16-31.x、192.168.x、0.0.0.0
       等），**始终拒绝**——这是 SSRF 的核心向量。
    2. **Hostname 白名单（opt-in）**：仅当环境变量 ``ALLOWED_LLM_HOSTS``
       被设置时启用主机名白名单；未设置时允许任意非保留-IP 的 hostname
       （支持私有 LLM 部署，deepseek_provider 文档明确支持
       ``LLM_BASE_URL`` 覆盖）。

    不做 DNS 解析后的 IP 检查 —— 沙箱 / CI 环境 DNS 劫持公网域名到本地
    IP 会误杀合法主机，且 hostname→IP 的 DNS rebinding 攻击面远小于
    直接 IP 字面量注入。

    Returns
    -------
    str
        校验通过的 base_url（原样返回）。

    Raises
    ------
    ValueError
        host 为保留 / 私网 IP 字面量，或（白名单启用时）host 不在白名单。
    """
    if not base_url:
        raise ValueError("LLM_BASE_URL is empty")

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"LLM_BASE_URL has no host: {base_url!r}")

    # 1) IP 字面量硬门 —— 始终拦截保留 / 私网 IP
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # 是 hostname，不是 IP 字面量
    if ip is not None and _is_reserved_ip(str(ip)):
        raise ValueError(
            f"LLM_BASE_URL host {host!r} is a reserved/private IP — "
            f"SSRF blocked"
        )

    # 2) Hostname 白名单（仅 ALLOWED_LLM_HOSTS 设置时启用）
    allowed = _allowed_hosts()
    if allowed:
        if host not in allowed:
            raise ValueError(
                f"LLM_BASE_URL host {host!r} not in allowlist "
                f"{sorted(allowed)}. "
                f"Adjust ALLOWED_LLM_HOSTS env (comma-separated) or unset "
                f"to allow any non-reserved-IP host."
            )

    return base_url


def validate_llm_model(model: str) -> str:
    """校验 LLM model 名称是否匹配允许的前缀。

    Raises
    ------
    ValueError
        model 不匹配任何允许前缀。
    """
    if not model:
        raise ValueError("LLM_MODEL is empty")
    model_lower = model.lower()
    for prefix in _allowed_model_prefixes():
        if model_lower.startswith(prefix):
            return model
    raise ValueError(
        f"LLM_MODEL {model!r} does not match any allowed prefix "
        f"{sorted(_allowed_model_prefixes())}. "
        f"Extend via ALLOWED_LLM_MODEL_PREFIXES env (comma-separated)."
    )


def safe_validate(
    base_url: str, model: str, *, provider_name: str = "unknown"
) -> bool:
    """便捷封装：校验通过返回 True，失败记 warning 并返回 False。

    供 ``read_*_config_from_env`` 使用：校验失败时返回 False，
    调用方据此回退到 MockProvider（fail-safe）。
    """
    try:
        validate_llm_base_url(base_url)
        validate_llm_model(model)
        return True
    except ValueError as exc:
        logger.warning(
            "[allowlist] %s provider config rejected (falling back to mock): %s",
            provider_name,
            exc,
        )
        return False


__all__ = [
    "validate_llm_base_url",
    "validate_llm_model",
    "safe_validate",
]
