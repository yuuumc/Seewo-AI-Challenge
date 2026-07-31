"""PG 数据模型：8 张核心表（V1.0）+ 4 张组织树表（V2.0 Sprint 5）.

V1.0: users / classes / homeworks / submissions / grading_results / corrections / analytics_snapshots / agent_trace
V2.0 Sprint 5: schools / grades / subject_groups（classes 表改造加 school_id/grade_id）
V2.0 Sprint 5: 7 张业务表加 school_id 字段（多租户隔离键）

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


# —————— 学校表（V2.0 Sprint 5） ——————
class School(Base):
    """学校表 — 多租户根表。"""

    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    district: Mapped[Optional[str]] = mapped_column(String(64))
    school_type: Mapped[str] = mapped_column(String(16), nullable=False, default="secondary")
    address: Mapped[Optional[str]] = mapped_column(String(256))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_schools_code", "code", unique=True),
    )


# —————— 年级表（V2.0 Sprint 5） ——————
class Grade(Base):
    """年级表 — 学校下的年级。"""

    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    grade_level: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(16), nullable=False, default="2026-2027")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_grades_school", "school_id", "grade_level"),
    )


# —————— 用户表 ——————
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="student")
    # teacher / head / admin / student / super_admin / school_admin / head_teacher / parent
    display_name: Mapped[Optional[str]] = mapped_column(String(64))
    avatar_color: Mapped[Optional[str]] = mapped_column(String(16))
    student_level: Mapped[Optional[str]] = mapped_column(String(4))
    # Sprint 4 P0-3: 家长知情同意
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # V2.0 Sprint 5: 多租户隔离键
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )
    # V2.0 Sprint 5: 家长关联子女 student_id 列表
    parent_of: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # V2.0 Sprint 5: 加密的 PII 字段（pgcrypto / AES-GCM，应用层加解密）
    pii_encrypted: Mapped[Optional[str]] = mapped_column(Text)
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

    __table_args__ = (
        Index("ix_users_school", "school_id"),
    )


# —————— 班级表（V2.0 Sprint 5 改造） ——————
class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    grade_year: Mapped[Optional[str]] = mapped_column(String(16))
    # V2.0 Sprint 5: 多租户 + 组织树
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )
    grade_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("grades.id", ondelete="SET NULL"),
    )
    class_code: Mapped[Optional[str]] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    teacher: Mapped["User"] = relationship(back_populates="classes_teaching", foreign_keys=[teacher_id])

    __table_args__ = (
        Index("ix_classes_school_grade", "school_id", "grade_id"),
    )


# —————— 学科组表（V2.0 Sprint 5） ——————
class SubjectGroup(Base):
    """学科组表 — 按学校+学科组织教师。"""

    __tablename__ = "subject_groups"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(32), nullable=False)
    leader_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
    )
    member_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_subject_groups_school", "school_id", "subject"),
    )


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
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    is_correct: Mapped[Optional[bool]] = mapped_column()
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    grader_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    # V2.0 Sprint 5: 多租户隔离键
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_grading_student_class", "student_id", "class_id"),
        Index("ix_grading_exam_question", "exam_id", "question_id"),
        Index("ix_grading_school", "school_id"),
    )


# —————— Agent 执行轨迹表 ——————
class AgentTrace(Base):
    __tablename__ = "agent_trace"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[Optional[int]] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # V2.0 Sprint 5: 审计用 school_id（agent_trace 不加 RLS，系统级日志跨租户可见）
    school_id: Mapped[Optional[int]] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_trace_agent_created", "agent_name", "created_at"),)


# —————— 作业表（V1.0 Sprint 1） ——————
class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    hw_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(32), nullable=False, default="数学")
    grade: Mapped[Optional[str]] = mapped_column(String(32))
    knowledge_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # V2.0 Sprint 5: 多租户隔离键
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    submissions: Mapped[list["Submission"]] = relationship(back_populates="homework")

    __table_args__ = (
        Index("ix_homeworks_school", "school_id"),
    )


# —————— 提交表（V1.0 Sprint 1） ——————
class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    homework_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("homeworks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submission_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    answers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # V2.0 Sprint 5: 多租户隔离键
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )

    student: Mapped["User"] = relationship(back_populates="submissions", foreign_keys=[student_id])
    homework: Mapped["Homework"] = relationship(back_populates="submissions")

    __table_args__ = (
        Index("ix_submission_student_hw", "student_id", "homework_id"),
        Index("ix_submission_school", "school_id"),
    )


# —————— 订正表（V1.0 Sprint 1） ——————
class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    homework_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(32), nullable=False)
    original_answer: Mapped[Optional[str]] = mapped_column(Text)
    attempts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # V2.0 Sprint 5: 多租户隔离键
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_correction_student_hw_q", "student_id", "homework_key", "question_id"),
        Index("ix_correction_school", "school_id"),
    )


# —————— 分析快照表（V1.0 Sprint 1） ——————
class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # V2.0 Sprint 5: 多租户隔离键
    school_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("schools.id", ondelete="RESTRICT"), nullable=False, default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_analytics_student_type", "student_id", "snapshot_type"),
        Index("ix_analytics_school", "school_id"),
    )


__all__ = [
    "Base",
    "School",
    "Grade",
    "User",
    "Class",
    "SubjectGroup",
    "GradingResult",
    "AgentTrace",
    "Homework",
    "Submission",
    "Correction",
    "AnalyticsSnapshot",
]
