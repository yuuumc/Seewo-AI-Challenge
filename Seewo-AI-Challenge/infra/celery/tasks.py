"""Celery 短任务：Phase 1 Week 2.

Week 2 改动：
  - P0-5: 重试加 jitter（避免多 worker 同步打峰触发上游 rate limit）
  - grade_choice 走 default 队列，keep sync
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone

import redis as redis_sync

from demo.fastapi_app.config import get_settings
from demo.engine.grader import grade_choice as engine_grade_choice
from infra.celery.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

_redis = redis_sync.from_url(settings.redis_url, decode_responses=True)


def _jittered_countdown(retries: int, base: int = 2, cap: int = 60, jitter: float = 3.0) -> float:
    """P0-5: 指数退避 + 随机 jitter.

    公式：countdown = min(2**retries, cap) + uniform(0, jitter)
    例：retries=0 → 1+[0,3]s；retries=2 → 4+[0,3]s；retries=10 → 60+[0,3]s
    """
    return min(base ** retries, cap) + random.uniform(0, jitter)


# —————— 批改任务（短） ——————
@celery_app.task(
    name="infra.celery.tasks.grade_choice",
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=False,  # 我们手算 jitter
    retry_jitter=False,
)
def grade_choice_task(
    self,
    student_answer: str,
    correct_answer: str,
    question_id: str = "unknown",
) -> dict:
    """异步批改选择题。Week 1 直接调同步引擎，Week 3 切到 C-08 真 LLM."""
    start = time.monotonic()
    try:
        result = engine_grade_choice(
            student_answer=student_answer,
            correct_answer=correct_answer,
        )
        result["question_id"] = question_id
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        logger.info("grade_choice done question_id=%s latency=%dms", question_id, result["latency_ms"])
        return result
    except Exception as exc:
        logger.exception("grade_choice failed question_id=%s", question_id)
        raise self.retry(
            exc=exc,
            countdown=_jittered_countdown(self.request.retries),
        ) from exc


# —————— 维护任务（beat 调度） ——————
@celery_app.task(name="infra.celery.tasks.cleanup_expired_sessions")
def cleanup_expired_sessions(ttl_seconds: int = 86400 * 7) -> int:
    """清理超过 7 天未访问的 Redis session key."""
    deleted = 0
    for key in _redis.scan_iter(match="session:*", count=200):
        last_seen = _redis.hget(key, "last_seen")
        if not last_seen:
            continue
        try:
            ts = datetime.fromisoformat(last_seen)
        except ValueError:
            _redis.delete(key)
            deleted += 1
            continue
        if datetime.now(timezone.utc) - ts > timedelta(seconds=ttl_seconds):
            _redis.delete(key)
            deleted += 1
    logger.info("cleanup_expired_sessions deleted=%d", deleted)
    return deleted


@celery_app.task(name="infra.celery.tasks.retry_failed_traces")
def retry_failed_traces(lookback_minutes: int = 30) -> int:
    """扫描最近 30 分钟内 status=failed 的 agent_trace，触发重试（占位实现）.

    Week 3 接 P1-5 索引后接实际重试逻辑。
    """
    logger.info("retry_failed_traces scan lookback=%dmin", lookback_minutes)
    return 0
