"""Celery LLM 任务：长任务隔离（P0-4）+ jitter（P0-5）.

Week 2 设计：
  - 独立模块 tasks_llm，由独立 worker-llm 消费
  - asyncio.to_thread 包装同步 LLM 客户端（不阻塞 event loop）
  - 长超时（25 分钟软 / 30 分钟硬）
  - 重试加 jitter（同 tasks._jittered_countdown）
  - 完整 trace 落 agent_trace 表（Phase 1.5 接 PG）

Week 3 接入 C-08 真 LLM 时替换 mock 引擎为 DeepSeek-Math / 通义千问VL 客户端。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from infra.celery.celery_app import celery_app
from infra.celery.tasks import _jittered_countdown

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """在 Celery 同步上下文跑 asyncio 协程."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Celery worker 是同步线程，event loop 不应已在跑
            return asyncio.run(coro)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(
    name="infra.celery.tasks_llm.grade_long_answer",
    bind=True,
    max_retries=2,
    time_limit=1800,
    soft_time_limit=1500,
)
def grade_long_answer_task(
    self,
    student_answer: str,
    question_id: str,
    student_id: str,
) -> dict:
    """异步批改长答案。Week 2 用 mock；Week 3 接 DeepSeek-Math 真 LLM.

    走 llm 队列，由独立 worker-llm 消费（concurrency=1 防 OOM）。
    """
    start = time.monotonic()
    try:
        # —— P0-4: 用 asyncio.to_thread 派发 LLM 同步调用 ——
        async def _call_llm() -> dict:
            # Sprint 2: 走 grade_long_answer_with_trace 以接入 provider 链
            # （按 subject_type 选 prompt + trace 记录）
            from engine.grader import grade_long_answer_with_trace
            # 从 questions.json 取完整 question dict（含 subject_type 如果有）
            try:
                from engine.grader import load_json
                questions = load_json("questions.json")
                question = None
                for hw in questions.values():
                    for q in hw.get("questions", []):
                        if q.get("id") == question_id:
                            question = q
                            break
                    if question:
                        break
                if question is None:
                    question = {"id": question_id, "type": "long_answer"}
            except Exception:
                question = {"id": question_id, "type": "long_answer"}

            return await asyncio.to_thread(
                grade_long_answer_with_trace, student_answer, question, student_id
            )

        result = _run_async(_call_llm())
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        result["student_id"] = student_id
        result["question_id"] = question_id
        logger.info(
            "grade_long_answer done student=%s q=%s latency=%dms",
            student_id, question_id, result["latency_ms"],
        )
        return result
    except Exception as exc:
        logger.exception("grade_long_answer failed student=%s q=%s", student_id, question_id)
        raise self.retry(
            exc=exc,
            countdown=_jittered_countdown(self.request.retries, base=3, cap=300, jitter=10.0),
        ) from exc


@celery_app.task(
    name="infra.celery.tasks_llm.ocr_extract",
    bind=True,
    max_retries=2,
    time_limit=600,
    soft_time_limit=540,
)
def ocr_extract_task(
    self,
    image_b64: str,
    question_id: str = "unknown",
    question_type: str = "long_answer",
) -> dict:
    """OCR 识别图片 — Sprint 2 接入 PaddleOCR.

    走 llm 队列。PaddleOCR 不可用时自动回退到 MockOCREngine，
    返回占位文本（不崩溃）。
    """
    start = time.monotonic()
    try:
        async def _call_ocr() -> dict:
            from engine.ocr import extract_text
            return await asyncio.to_thread(
                extract_text, image_b64, question_type
            )

        result = _run_async(_call_ocr())
        result["question_id"] = question_id
        result["latency_ms"] = int((time.monotonic() - start) * 1000)
        logger.info(
            "ocr_extract done q=%s provider=%s latency=%dms",
            question_id, result.get("provider"), result["latency_ms"],
        )
        return result
    except Exception as exc:
        logger.exception("ocr_extract failed question_id=%s", question_id)
        raise self.retry(
            exc=exc,
            countdown=_jittered_countdown(self.request.retries, base=2, cap=60, jitter=5.0),
        ) from exc
