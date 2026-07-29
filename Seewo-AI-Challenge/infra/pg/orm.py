"""PG 数据模型：4 张核心表（users / classes / grading_results / agent_trace）.

SQLAlchemy 2.x 风格：`DeclarativeBase` + `Mapped[T]` + `mapped_column`。
配套 Alembic 迁移脚本在 `infra/pg/migrations/`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """所有模型的基类。"""


# —————— 用户表 ——————
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="student")
    # teacher / head / admin / student
    display_name: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # 反向关系
    classes_teaching: Mapped[list["Class"]] = relationship(
        back_populates="teacher", foreign_keys="Class.teacher_id"
    )


# —————— 班级表 ——————
class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    grade_year: Mapped[Optional[str]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    teacher: Mapped["User"] = relationship(back_populates="classes_teaching", foreign_keys=[teacher_id])


# —————— 批改结果表 ——————
class GradingResult(Base):
    __tablename__ = "grading_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("classes.id", ondelete="SET NULL")
    )
    exam_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)
    question_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # choice / fill_blank / long_answer
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    is_correct: Mapped[Optional[bool]] = mapped_column()
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    grader_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_grading_student_class", "student_id", "class_id"),
        Index("ix_grading_exam_question", "exam_id", "question_id"),
    )


# —————— Agent 执行轨迹表（C-08 LLM 接入后高频写入） ——————
class AgentTrace(Base):
    __tablename__ = "agent_trace"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # grader / comment_writer / analytics / ocr
    task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # 关联 Celery task id
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    # success / failed / timeout
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_trace_agent_created", "agent_name", "created_at"),)


__all__ = ["Base", "User", "Class", "GradingResult", "AgentTrace"]
