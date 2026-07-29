"""Phase 1 FastAPI 入口：uvicorn 启动此文件.

Week 2 改动：
  1. /api/v1/health 拆为 /healthz（liveness）+ /readyz（readiness），PG/Redis 失败 readyz 返 503
  2. lifespan 启动期检查 demo_mode 与 env 的组合（生产禁 demo）
  3. 错误处理：401/403/429 走标准 HTTPException

不动 demo/app.py——保留 Flask 28 路由稳定。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy import text
from starlette.middleware.wsgi import WSGIMiddleware

from demo.app import app as flask_app  # 复用 Phase 0 整合的 Flask 单体
from demo.fastapi_app.config import get_settings
from demo.fastapi_app.deps import dispose_db, get_redis
from demo.fastapi_app.routes import grade

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """启动：建立 DB/Redis 连接池；关闭：优雅释放."""
    # P0-2 / 队长 P0 条件：生产环境 demo_mode 必须 False（已被 model_validator 拦截）
    if settings.env == "production" and settings.demo_mode:
        raise RuntimeError("demo_mode=True 不允许在 production 环境启动")
    logger.info(
        "Phase 1 FastAPI 启动  env=%s demo_mode=%s log_level=%s",
        settings.env, settings.demo_mode, settings.log_level,
    )
    yield
    logger.info("Phase 1 FastAPI 关闭 释放连接池")
    await dispose_db()


def create_app() -> FastAPI:
    """应用工厂（便于测试用 `create_app()` 多次实例化）。"""
    application = FastAPI(
        title="Seewo AI Challenge API",
        version="1.1.0-phase2",
        description="Phase 1 Week 2：FastAPI 入口 + Flask 兼容层 + 鉴权 Depends + Celery 异步 + 拆分健康检查",
        lifespan=lifespan,
    )

    # —— 新 FastAPI 路由（先注册，路由匹配优先级高于 WSGIMiddleware 挂载） ——
    application.include_router(grade.router, prefix="/api/v1/grade", tags=["grading"])

    @application.get("/api/v1/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        """Liveness probe：进程存活即 OK，不查依赖。供 k8s livenessProbe / Docker HEALTHCHECK。"""
        return {"status": "ok"}

    @application.get("/api/v1/readyz", tags=["meta"])
    async def readyz() -> dict[str, object]:
        """Readiness probe：PG + Redis 都通才 200；任一失败返 503。供 k8s readinessProbe / LB 探活。"""
        from demo.fastapi_app.deps import _session_factory
        from fastapi.responses import JSONResponse

        pg_ok = False
        pg_err = ""
        try:
            async with _session_factory() as session:
                await session.execute(text("SELECT 1"))
            pg_ok = True
        except Exception as exc:  # noqa: BLE001
            pg_err = str(exc)
            logger.warning("readyz: PG failed: %s", exc)

        redis_ok = False
        redis_err = ""
        try:
            r = get_redis()
            await r.ping()
            redis_ok = True
        except Exception as exc:  # noqa: BLE001
            redis_err = str(exc)
            logger.warning("readyz: Redis failed: %s", exc)

        ready = pg_ok and redis_ok
        body = {
            "ready": ready,
            "env": settings.env,
            "checks": {
                "postgres": {"ok": pg_ok, "error": pg_err},
                "redis":    {"ok": redis_ok, "error": redis_err},
            },
        }
        return JSONResponse(status_code=200 if ready else 503, content=body)

    # —— Flask 兼容层：所有未匹配的路径回退到老 Flask app ——
    application.mount("/", WSGIMiddleware(flask_app))

    return application


# uvicorn demo.fastapi_app.main:app --host 0.0.0.0 --port 8000
app = create_app()
