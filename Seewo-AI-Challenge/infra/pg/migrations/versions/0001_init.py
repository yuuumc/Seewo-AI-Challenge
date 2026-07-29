"""Initial schema: users / classes / grading_results / agent_trace

Revision ID: 0001_init
Revises:
Create Date: 2026-07-28 (Week 1)
Week 2 Update: 补齐 P0-3 缺失的 4 个索引：
  - ix_grading_student_class
  - ix_grading_exam_question
  - ix_trace_user
  - ix_trace_agent_time
原 schema.sql 已删除（P0-3 修复），本迁移为 schema 唯一真相源。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="student"),
        sa.Column("display_name", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "classes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("teacher_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grade_year", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_classes_teacher", "classes", ["teacher_id"])

    op.create_table(
        "grading_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", sa.BigInteger(), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("exam_id", sa.String(64)),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("question_type", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_score", sa.Float(), nullable=False, server_default="100"),
        sa.Column("is_correct", sa.Boolean()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("grader_version", sa.String(16), nullable=False, server_default="v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_grading_student", "grading_results", ["student_id"])
    op.create_index("ix_grading_class", "grading_results", ["class_id"])
    op.create_index("ix_grading_exam", "grading_results", ["exam_id"])
    op.create_index("ix_grading_created", "grading_results", ["created_at"])
    # —— P0-3 补齐：原 schema.sql 里有，0001_init.py 漏的 2 个复合索引 ——
    op.create_index("ix_grading_student_class", "grading_results", ["student_id", "class_id"])
    op.create_index("ix_grading_exam_question", "grading_results", ["exam_id", "question_id"])

    op.create_table(
        "agent_trace",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64)),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.BigInteger()),
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_trace_agent", "agent_trace", ["agent_name"])
    op.create_index("ix_trace_task", "agent_trace", ["task_id"])
    op.create_index("ix_trace_created", "agent_trace", ["created_at"])
    # —— P0-3 补齐：原 schema.sql 里有，0001_init.py 漏的 2 个索引 ——
    op.create_index("ix_trace_user", "agent_trace", ["user_id"])
    op.create_index("ix_trace_agent_time", "agent_trace", ["agent_name", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_trace")
    op.drop_table("grading_results")
    op.drop_table("classes")
    op.drop_table("users")
