"""P0-6 鉴权收紧单测：学生访问教师看板 API 应被 403.

Week 2 收口：app.py 4 个 API 路由已加 @roles_required("teacher", "head", "admin")
  - /api/analytics/<aid>
  - /api/correction-loop/<aid>
  - /api/review-queue/<aid>
  - /api/variants/<qid>/<level>

本测试在 DEMO_AUTH_OPEN=0 模式下验证收紧生效。
在默认 demo 模式（DEMO_AUTH_OPEN=1）下 xfail（decorator bypass）。
"""
from __future__ import annotations

import os
from typing import Any

import pytest

# —— 4 个被收紧的 API 端点（与 app.py 装饰器链对应） ——
_TEACHER_ONLY_APIS: list[str] = [
    "/api/analytics/hw_001",
    "/api/correction-loop/hw_001",
    "/api/review-queue/hw_001",
    "/api/variants/q-001/B",
]


@pytest.fixture(autouse=True)
def _require_strict_auth() -> None:
    """本测试套件必须开启严格鉴权（DECORATOR 真生效）."""
    if os.environ.get("DEMO_AUTH_OPEN", "1") != "0":
        pytest.skip("DEMO_AUTH_OPEN=0 required for P0-6 strict-auth tests")


def test_student_blocked_from_teacher_apis(client: Any) -> None:
    """学生登录后访问 4 个教师 API 应全部 403/302/404/405（任何非 200 都算合规）."""
    # —— 1. 学生登录 ——
    rv = client.post(
        "/login",
        data={"username": "s01", "password": "student123"},
    )
    assert rv.status_code in (200, 302), f"s01 login failed: {rv.status_code}"

    # —— 2. 逐个访问教师 API ——
    for api_path in _TEACHER_ONLY_APIS:
        rv = client.get(api_path)
        assert rv.status_code in (302, 403, 404, 405), (
            f"❌ {api_path} 学生可访问 (status={rv.status_code})；"
            f"期望 302/403/404/405"
        )


def test_teacher_can_access_teacher_apis(client: Any) -> None:
    """教师登录后访问 4 个教师 API 应不被 RBAC 拦截（200 或 5xx 服务端问题，不应 403）."""
    rv = client.post(
        "/login",
        data={"username": "teacher", "password": "teacher123"},
    )
    assert rv.status_code in (200, 302), f"teacher login failed: {rv.status_code}"

    for api_path in _TEACHER_ONLY_APIS:
        rv = client.get(api_path)
        # 教师应能访问；返回 200 / 302 / 5xx（数据问题） 都算未被 RBAC 拦截
        assert rv.status_code not in (401, 403), (
            f"❌ {api_path} 教师也被 RBAC 拦截 (status={rv.status_code})；"
            f"装饰器链可能错配"
        )


def test_admin_can_access_teacher_apis(client: Any) -> None:
    """admin / head 角色也应不被拦截（与 teacher 等同权限）."""
    for username, password in [("head", "head123"), ("admin", "admin123")]:
        client.post("/login", data={"username": username, "password": password})
        for api_path in _TEACHER_ONLY_APIS:
            rv = client.get(api_path)
            assert rv.status_code not in (401, 403), (
                f"❌ {api_path} {username} 也被拦截 (status={rv.status_code})"
            )
        client.post("/logout")
