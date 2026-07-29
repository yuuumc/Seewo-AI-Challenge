"""新异步 grading API：派发到 Celery，不阻塞请求线程.

Week 2 改动（P0-6）：所有路由加 Depends(get_current_user)；
  - 短任务 grade_choice 走 default 队列
  - 长任务 grade_long_answer / ocr_extract 走 llm 队列（独立 worker）
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from demo.fastapi_app.security import get_current_user
from infra.celery.tasks import grade_choice_task
from infra.celery.tasks_llm import grade_long_answer_task, ocr_extract_task

router = APIRouter()


@router.post(
    "/choice",
    summary="异步批改选择题",
    dependencies=[Depends(get_current_user)],
)
async def grade_choice(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """派发选择题批改到 Celery worker（default 队列）.

    需登录。Body 必填：student_answer, correct_answer。
    """
    try:
        task = grade_choice_task.apply_async(
            kwargs={
                "student_answer": payload["student_answer"],
                "correct_answer": payload["correct_answer"],
                "question_id":    payload.get("question_id", "unknown"),
            },
            queue="default",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing field: {exc.args[0]}",
        ) from exc
    return {"task_id": task.id, "status": "queued", "user_id": user.get("user_id")}


@router.post(
    "/long-answer",
    summary="异步批改长答案（走 LLM 队列）",
    dependencies=[Depends(get_current_user)],
)
async def grade_long_answer(payload: dict) -> dict:
    """派发长答案批改到 worker-llm 队列（P0-4 隔离）.

    Body 必填：student_answer, question_id, student_id。
    """
    try:
        task = grade_long_answer_task.apply_async(
            kwargs={
                "student_answer": payload["student_answer"],
                "question_id":    payload["question_id"],
                "student_id":     payload["student_id"],
            },
            queue="llm",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing field: {exc.args[0]}",
        ) from exc
    return {"task_id": task.id, "status": "queued", "queue": "llm"}


@router.post(
    "/ocr",
    summary="OCR 识别图片（走 LLM 队列）",
    dependencies=[Depends(get_current_user)],
)
async def ocr_extract(payload: dict) -> dict:
    """派发 OCR 任务到 worker-llm 队列.

    Body 必填：image_b64 (base64 encoded image), question_id。
    """
    try:
        task = ocr_extract_task.apply_async(
            kwargs={
                "image_b64":   payload["image_b64"],
                "question_id": payload.get("question_id", "unknown"),
            },
            queue="llm",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing field: {exc.args[0]}",
        ) from exc
    return {"task_id": task.id, "status": "queued", "queue": "llm"}


@router.get(
    "/status/{task_id}",
    summary="查询批改任务状态",
    dependencies=[Depends(get_current_user)],
)
async def task_status(task_id: str) -> dict:
    """非阻塞查询 Celery 任务状态（P1-3 修复：asyncio.to_thread）."""
    from infra.celery.celery_app import celery_app

    def _fetch() -> dict:
        res = celery_app.AsyncResult(task_id)
        return {
            "state": res.state,
            "ready": res.ready(),
            "result": res.result if res.ready() and not res.failed() else None,
        }

    body = await asyncio.to_thread(_fetch)
    return {"task_id": task_id, **body}
