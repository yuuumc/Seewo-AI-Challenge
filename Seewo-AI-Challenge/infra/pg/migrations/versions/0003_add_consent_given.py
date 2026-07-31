"""Sprint 4 P0-3: add consent_given column to users table.

Revision ID: 0003_add_consent_given
Revises: 0002_add_v1_tables
Create Date: 2026-07-30 (Sprint 4)

Changes:
  - users: add consent_given boolean (default False)
    Tracks whether a student's parent/guardian has given informed
    consent for the processing of minor's learning data.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_add_consent_given"
down_revision = "0002_add_v1_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("consent_given", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "consent_given")
