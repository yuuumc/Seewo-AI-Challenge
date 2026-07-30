"""新异步 grading API：派发到 Celery，不阻塞请求线程.

Week 2 改动（P0-6）：所有路由加 Depends(get_current_user)；
  - 短任务 grade_choice 走 default 队列
  - 长任务 grade_long_answer / ocr_extract 走 llm 队列（独立 worker）

Sprint 2 改动（提示词工程师线）：
  - 新增 POST /e2e 端到端批改路由：学生提交 → 按 subject_type 选 prompt
    → 调 LLM/mock → 结构化结果 → 写 grading_results 表
  - 不经 Celery，直接在 async 路由内 asyncio.to_thread 调同步 provider
    （mock 模式零延迟；真 LLM 模式由 OpenAIProvider 自带 timeout+retry）
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from demo.fastapi_app.security import get_current_user
from infra.celery.tasks import grade_choice_task
from infra.celery.tasks_llm import grade_long_answer_task, ocr_extract_task

logger = logging.getLogger(__name__)

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
    Body 可选：question_type (默认 long_answer)。
    """
    try:
        task = ocr_extract_task.apply_async(
            kwargs={
                "image_b64":     payload["image_b64"],
                "question_id":   payload.get("question_id", "unknown"),
                "question_type": payload.get("question_type", "long_answer"),
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


# ── Sprint 2: 端到端批改（不经 Celery，直接调 provider） ──────────────


class E2EGradeRequest(BaseModel):
    """端到端批改请求体.

    question 字段需包含 subject_type（7 学科之一）以触发多学科 prompt 分发。
    缺少 subject_type 时回退到 math_step_grading（向后兼容 Sprint 1）。
    """

    student_answer: str = Field(..., description="学生答案文本")
    question: Dict[str, Any] = Field(
        ..., description="题目 dict（含 id/type/stem/score/answer/subject_type 等）"
    )
    student_id: str = Field(..., description="学生 ID，如 s02")
    assignment_id: str = Field("hw_001", description="作业 ID")


class E2EGradeResponse(BaseModel):
    """端到端批改响应体（结构化结果）."""

    student_id: str
    assignment_id: str
    question_id: str
    subject_type: str
    is_correct: bool
    score: float
    max_score: float
    step_results: list
    error_types: list
    ai_confidence: float
    overall_feedback: str
    need_teacher_review: bool
    provider: str
    persisted: bool = Field(False, description="是否已写入 grading_results 表")


def _do_grade_sync(
    student_answer: str,
    question: Dict[str, Any],
    student_id: str,
    assignment_id: str,
) -> Dict[str, Any]:
    """同步调用 provider 链（在 asyncio.to_thread 中运行）.

    走 ``engine.grader.grade_long_answer_with_trace`` —— 它内部:
      1. 从 factory 取 provider（mock / openai / deepseek）
      2. 创建 TraceCollector
      3. 调 provider.grade_step(question=..., trace=...)
         → provider 按 question.subject_type 选 prompt
      4. 存 trace 到 in-process store
      5. 返回结构化 dict
    """
    import sys
    from pathlib import Path

    # 确保 demo/ 在 sys.path（Celery worker 可能不挂 demo/）
    demo_dir = str(Path(__file__).resolve().parent.parent.parent)
    if demo_dir not in sys.path:
        sys.path.insert(0, demo_dir)

    from engine.grader import grade_long_answer_with_trace

    return grade_long_answer_with_trace(
        student_answer, question, student_id, assignment_id
    )


def _persist_grading_result(
    student_id: str,
    assignment_id: str,
    question: Dict[str, Any],
    result: Dict[str, Any],
) -> bool:
    """将批改结果写入 grading_results 表（PG 可达时）.

    返回 True 表示已持久化；False 表示 PG 不可达或写入失败（不阻塞响应）。
    """
    try:
        from db_store import is_pg_available, _get_pg_engine
        if not is_pg_available():
            return False

        from infra.pg.orm import GradingResult
        from sqlalchemy.orm import Session

        engine = _get_pg_engine()
        if engine is None:
            return False

        # student_id 在 PG 中是 users.id (BigInteger)。
        # demo 模式下 student_id 是 "s02" 这种字符串，需要查 users 表拿数字 id。
        # 这里做 best-effort：如果 student_id 是纯数字就用，否则跳过持久化。
        try:
            student_db_id = int(student_id)
        except (ValueError, TypeError):
            # 尝试按 username 查 PG users 表
            try:
                from infra.pg.orm import User
                from sqlalchemy import select
                with Session(engine) as session:
                    user = session.execute(
                        select(User).where(User.username == student_id)
                    ).scalar_one_or_none()
                    if user is None:
                        return False
                    student_db_id = user.id
            except Exception:
                return False

        question_type = question.get("type", "long_answer")
        max_score = float(question.get("score", result.get("max_score", 0)))

        details = {
            "step_results": result.get("step_results", []),
            "error_types": result.get("error_types", []),
            "overall_feedback": result.get("overall_feedback", ""),
            "subject_type": question.get("subject_type", "math_calculation"),
            "student_answer": result.get("student_answer", ""),
            "correct_answer": result.get("correct_answer", ""),
        }

        with Session(engine) as session:
            gr = GradingResult(
                student_id=student_db_id,
                exam_id=assignment_id,
                question_id=str(question.get("id", "unknown")),
                question_type=question_type,
                score=float(result.get("score", 0)),
                max_score=max_score,
                is_correct=bool(result.get("is_correct", False)),
                details=details,
                grader_version="v1-sprint2",
            )
            session.add(gr)
            session.commit()
        return True
    except Exception as exc:
        logger.warning("persist grading_result failed: %s", exc)
        return False


@router.post(
    "/e2e",
    summary="端到端批改（多学科 prompt 分发 + 结构化结果 + PG 持久化）",
    dependencies=[Depends(get_current_user)],
    response_model=E2EGradeResponse,
)
async def grade_e2e(payload: E2EGradeRequest) -> E2EGradeResponse:
    """Sprint 2 端到端批改路由.

    流程:
      1. 学生提交答案 (student_answer + question with subject_type)
      2. grader 按 question.subject_type 选 prompt (get_prompt)
      3. 调 LLM provider (mock / openai / deepseek)
      4. 返回结构化结果 (step_results / error_types / confidence / overall_feedback)
      5. 写入 grading_results 表 (PG 可达时)

    mock 模式 (无 LLM_API_KEY): MockProvider 返回 fixture 结构化结果
    prod 模式 (有 LLM_API_KEY): OpenAIProvider/DeepSeekProvider 调真 LLM
    """
    # 1. 同步调用 provider 链（不阻塞 event loop）
    result = await asyncio.to_thread(
        _do_grade_sync,
        payload.student_answer,
        payload.question,
        payload.student_id,
        payload.assignment_id,
    )

    # 2. 持久化到 PG（best-effort，失败不阻塞响应）
    persisted = await asyncio.to_thread(
        _persist_grading_result,
        payload.student_id,
        payload.assignment_id,
        payload.question,
        result,
    )

    # 3. 判断 provider 来源
    try:
        from engine.llm import get_provider
        provider_name = get_provider().name
    except Exception:
        provider_name = "unknown"

    # 4. 组装结构化响应
    return E2EGradeResponse(
        student_id=payload.student_id,
        assignment_id=payload.assignment_id,
        question_id=str(payload.question.get("id", "unknown")),
        subject_type=payload.question.get("subject_type", "math_calculation"),
        is_correct=bool(result.get("is_correct", False)),
        score=float(result.get("score", 0)),
        max_score=float(result.get("max_score", payload.question.get("score", 0))),
        step_results=result.get("step_results", []),
        error_types=result.get("error_types", []),
        ai_confidence=float(result.get("ai_confidence", 0.0)),
        overall_feedback=result.get("overall_feedback", ""),
        need_teacher_review=bool(result.get("need_teacher_review", False)),
        provider=provider_name,
        persisted=persisted,
    )
