"""Tests 包的共享辅助 — 纯函数 / 数据，不放 fixture。

⚠️ pytest 约定：`conftest.py` 里的 fixture 会被自动发现，但 `from conftest import ...`
是被禁止的（pytest 不会把 conftest 视为普通模块）。所有需要跨文件共享的**常量 / 工具**
放这里，conftest.py 只放 fixture。
"""

from __future__ import annotations

import pytest

# ── 演示账号表（与前端 UI 线 CHANGES.md §2 完全对齐） ───────────────
DEMO_ACCOUNTS: dict[str, dict[str, str]] = {
    "teacher": {"username": "teacher", "password": "teacher123", "role": "teacher"},
    "head": {"username": "head", "password": "head123", "role": "head"},
    "admin": {"username": "admin", "password": "admin123", "role": "admin"},
    "s01": {"username": "s01", "password": "student123", "role": "student"},
    "s02": {"username": "s02", "password": "student123", "role": "student"},
    "s03": {"username": "s03", "password": "student123", "role": "student"},
    "s04": {"username": "s04", "password": "student123", "role": "student"},
    "s05": {"username": "s05", "password": "student123", "role": "student"},
}


def require_integration(condition: bool, item: str) -> None:
    """统一 xfail 文案 — leader 集成后 grep `TODO(leader-integration)` 即可看清单。"""
    if not condition:
        pytest.xfail(f"TODO(leader-integration): {item} 尚未集成")
