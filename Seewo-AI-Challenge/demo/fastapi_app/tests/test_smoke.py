"""FastAPI 端到端 smoke 测试：验证 lifespan / health / grade 派发链路."""
from __future__ import annotations

import os
import uuid

# 强制在 CI 环境启用 in-memory 替身（即使 PG/Redis 没起也能跑）
os.environ.setdefault("ENV", "test")

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_reachable() -> None:
    """健康检查端点可达（即使 PG/Redis 降级也算 200）。"""
    from demo.fastapi_app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"ok", "degraded"}
        assert "checks" in body
        assert "postgres" in body["checks"]
        assert "redis" in body["checks"]


@pytest.mark.asyncio
async def test_grade_choice_validation() -> None:
    """/api/v1/grade/choice 必填字段缺失应返回 400。"""
    from demo.fastapi_app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 缺 student_answer
        resp = await client.post("/api/v1/grade/choice", json={"correct_answer": "B"})
        assert resp.status_code == 422  # FastAPI 自动校验


@pytest.mark.asyncio
async def test_root_flask_fallback() -> None:
    """未匹配路径应回退到 Flask（即便 healthz 等由 Flask 提供）。"""
    from demo.fastapi_app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # /healthz 是 Flask 老路由，命中 WSGIMiddleware
        resp = await client.get("/healthz", follow_redirects=False)
        # Flask 可能重定向到 /login（200/302 都算可达）
        assert resp.status_code in {200, 302}
