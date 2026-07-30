"""V1.0 Sprint 1: add homeworks / submissions / corrections / analytics_snapshots + extend users

Revision ID: 0002_add_v1_tables
Revises: 0001_init
Create Date: 2026-07-30 (V1.0 Sprint 1)

Changes:
  - users: add avatar_color, student_level columns
  - homeworks: new table (from questions.json)
  - submissions: new table (from answers.json)
  - corrections: new table (from corrections.json)
  - analytics_snapshots: new table (from growth_report / dashboard / knowledge_tree)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_v1_tables"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # — Extend users table —
    op.add_column("users", sa.Column("avatar_color", sa.String(16)))
    op.add_column("users", sa.Column("student_level", sa.String(4)))

    # — homeworks —
    op.create_table(
        "homeworks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("hw_key", sa.String(64), nullable=False, unique=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("subject", sa.String(32), nullable=False, server_default="数学"),
        sa.Column("grade", sa.String(32)),
        sa.Column("knowledge_points", sa.JSON(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_homeworks_hw_key", "homeworks", ["hw_key"])

    # — submissions —
    op.create_table(
        "submissions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("homework_id", sa.BigInteger(), sa.ForeignKey("homeworks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_key", sa.String(64), nullable=False, unique=True),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_submission_student", "submissions", ["student_id"])
    op.create_index("ix_submission_homework", "submissions", ["homework_id"])
    op.create_index("ix_submission_student_hw", "submissions", ["student_id", "homework_id"])

    # — corrections —
    op.create_table(
        "corrections",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("homework_key", sa.String(64), nullable=False),
        sa.Column("question_id", sa.String(32), nullable=False),
        sa.Column("original_answer", sa.Text()),
        sa.Column("attempts", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_correction_student", "corrections", ["student_id"])
    op.create_index("ix_correction_hw", "corrections", ["homework_key"])
    op.create_index("ix_correction_student_hw_q", "corrections", ["student_id", "homework_key", "question_id"])

    # — analytics_snapshots —
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("student_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_type", sa.String(32), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_analytics_student", "analytics_snapshots", ["student_id"])
    op.create_index("ix_analytics_type", "analytics_snapshots", ["snapshot_type"])
    op.create_index("ix_analytics_student_type", "analytics_snapshots", ["student_id", "snapshot_type"])
    op.create_index("ix_analytics_created", "analytics_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_table("analytics_snapshots")
    op.drop_table("corrections")
    op.drop_table("submissions")
    op.drop_table("homeworks")
    op.drop_column("users", "student_level")
    op.drop_column("users", "avatar_color")
