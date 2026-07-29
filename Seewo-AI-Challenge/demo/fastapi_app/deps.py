"""Phase 1 依赖注入：DB session / Redis 客户端.

Week 2 改动：
  - 暴露 get_redis() 供 fastapi_app.security 共用 session 解码
  - 启动期用 get_settings() 单例注入（确保 model_validator 跑过）
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import redis.asyncio as redis_async
from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from demo.fastapi_app.config import get_settings

# —— 全局引擎 + session 工厂 ——
_settings = get_settings()
_engine = create_async_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,  # 连接前探活，PG 重启后自动恢复
    echo=False,
)
_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

# —— Redis 连接池 ——
_redis_pool = redis_async.ConnectionPool.from_url(
    _settings.redis_url,
    max_connections=20,
    decode_responses=True,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每次请求一个 session，结束自动 close。"""
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> redis_async.Redis:
    """FastAPI 依赖：返回共享 Redis 客户端。"""
    return redis_async.Redis(connection_pool=_redis_pool)


async def dispose_db() -> None:
    """lifespan shutdown 时调用：释放连接池。"""
    await _engine.dispose()
    await _redis_pool.disconnect()


__all__ = ["get_db", "get_redis", "dispose_db", "_session_factory"]
