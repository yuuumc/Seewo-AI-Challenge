"""PG 数据模型：7 张核心表（V1.0 Sprint 1）.

users / classes / homeworks / submissions / grading_results / corrections / analytics_snapshots

SQLAlchemy 2.x 风格：`DeclarativeBase` + `Mapped[T]` + `mapped_column`。
配套 Alembic 迁移脚本在 `infra/pg/migrations/`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
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

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="student")
    # teacher / head / admin / student
    display_name: Mapped[Optional[str]] = mapped_column(String(64))
    # V1.0: student display metadata (from students.json)
    avatar_color: Mapped[Optional[str]] = mapped_column(String(16))
    student_level: Mapped[Optional[str]] = mapped_column(String(4))
    # Sprint 4 P0-3: 家长知情同意（未成年学情数据使用）
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # 反向关系
    classes_teaching: Mapped[list["Class"]] = relationship(
        back_populates="teacher", foreign_keys="Class.teacher_id"
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="student", foreign_keys="Submission.student_id"
    )


# —————— 班级表 ——————
class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
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


# —————— 作业表（V1.0 Sprint 1） ——————
class Homework(Base):
    """作业定义，源自 questions.json 的 hw_001 结构。"""

    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    hw_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # e.g. "hw_001" — 与 JSON 文件 key 对齐
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(32), nullable=False, default="数学")
    grade: Mapped[Optional[str]] = mapped_column(String(32))
    knowledge_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 完整 questions 数组（含 stem/options/answer/score/knowledge）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 反向关系
    submissions: Mapped[list["Submission"]] = relationship(back_populates="homework")


# —————— 提交表（V1.0 Sprint 1） ——————
class Submission(Base):
    """学生提交的作答，源自 answers.json。"""

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    homework_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("homeworks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # e.g. "s01_hw_001" — 与 JSON key 对齐，防止重复导入
    answers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # {q1: "D", q2: "A", ...}
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 反向关系
    student: Mapped["User"] = relationship(back_populates="submissions", foreign_keys=[student_id])
    homework: Mapped["Homework"] = relationship(back_populates="submissions")

    __table_args__ = (
        Index("ix_submission_student_hw", "student_id", "homework_id"),
    )


# —————— 订正表（V1.0 Sprint 1） ——————
class Correction(Base):
    """订正记录，源自 corrections.json。"""

    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    homework_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # e.g. "hw_001" — 订正数据按 homework 聚合
    question_id: Mapped[str] = mapped_column(String(32), nullable=False)
    original_answer: Mapped[Optional[str]] = mapped_column(Text)
    attempts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{attempt: 1, content: "...", result: "correct", feedback: "..."}]
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # open / closed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_correction_student_hw_q", "student_id", "homework_key", "question_id"),
    )


# —————— 分析快照表（V1.0 Sprint 1） ——————
class AnalyticsSnapshot(Base):
    """学情分析快照，源自 growth_report / student_dashboard / knowledge_tree。"""

    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # growth_report / student_dashboard / knowledge_tree / knowledge_radar
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # 完整 JSON 结构原样存储
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_analytics_student_type", "student_id", "snapshot_type"),
    )


__all__ = [
    "Base",
    "User",
    "Class",
    "GradingResult",
    "AgentTrace",
    "Homework",
    "Submission",
    "Correction",
    "AnalyticsSnapshot",
]
