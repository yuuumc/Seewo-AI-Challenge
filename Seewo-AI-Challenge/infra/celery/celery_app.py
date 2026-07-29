"""Celery 应用工厂：Phase 1 异步任务底座.

Week 2 改动：
  1. 新增 llm 队列路由（task_routes）—— 短任务 default，长任务 llm
  2. llm 队列单独 time_limit（1800s）和 concurrency=1（防 OOM）
  3. broker_connection_retry_on_startup 已开（Week 1）

启动方式：
  - 默认 worker:  python -m infra.celery.worker        (消费 default 队列)
  - LLM worker:   python -m infra.celery.worker_llm     (消费 llm 队列)
  - 调度器:       python -m infra.celery.beat
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from demo.fastapi_app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "seewo_phase1",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "infra.celery.tasks",
        "infra.celery.tasks_llm",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,  # 任务完成后才 ack，worker 崩溃会重派
    worker_prefetch_multiplier=1,  # 长任务不要 prefetch
    broker_connection_retry_on_startup=True,
    # —— 队列路由：default 短任务 / llm 长任务 ——
    task_routes={
        "infra.celery.tasks.*":       {"queue": "default"},
        "infra.celery.tasks_llm.*":   {"queue": "llm"},
    },
    # —— 队列隔离配置：llm 队列单独超时 ——
    task_default_queue="default",
    # default 队列用 5 分钟软超时
    task_soft_time_limit=300,
    task_time_limit=600,
)

# —— Beat 调度（Week 1 草案，Week 2 不变） ——
celery_app.conf.beat_schedule = {
    "cleanup-expired-sessions-daily": {
        "task": "infra.celery.tasks.cleanup_expired_sessions",
        "schedule": crontab(hour=3, minute=0),
    },
    "retry-failed-agent-traces": {
        "task": "infra.celery.tasks.retry_failed_traces",
        "schedule": crontab(minute="*/5"),
    },
}


def llm_worker_app() -> Celery:
    """为 LLM worker 返回专门配置：长超时、低并发、仅 llm 队列."""
    cfg = celery_app.conf.copy()
    cfg.task_soft_time_limit = 1500  # 25 分钟
    cfg.task_time_limit = 1800       # 30 分钟硬超时
    cfg.worker_concurrency = 1       # 1 并发防 OOM
    cfg.task_default_queue = "llm"
    llm_app = Celery(
        "seewo_phase1_llm",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["infra.celery.tasks_llm"],
    )
    llm_app.conf.update(cfg)
    return llm_app


__all__ = ["celery_app", "llm_worker_app"]
