"""V2.0 Sprint 5: 组织树 4 新表 + 7 表 school_id + RLS 策略.

Revision ID: 0004_add_org_tree_multitenant
Revises: 0003_add_consent_given
Create Date: 2026-07-31 (Sprint 5)

Changes (9 steps):
  1. Create schools table
  2. Create grades table
  3. Create subject_groups table
  4. Add school_id to 7 business tables (users/classes/homeworks/submissions/grading_results/corrections/analytics_snapshots)
  5. Add grade_id/class_code/is_active to classes table
  6. Insert default school (id=1)
  7. Backfill school_id=1 for existing rows
  8. Create indexes
  9. Enable PG RLS + CREATE POLICY (PG only; SQLite skipped)

Review fixes incorporated:
  - school_id uses BigInteger (consistent with schools.id)
  - RLS covers 11 tables: 7 business + grades + subject_groups + classes + users
  - DDL is the single source of truth (migrate_to_multitenant.py does not duplicate DDL)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_add_org_tree_multitenant"
down_revision = "0003_add_consent_given"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Create schools table
    op.create_table(
        "schools",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("district", sa.String(64)),
        sa.Column("school_type", sa.String(16), nullable=False, server_default="secondary"),
        sa.Column("address", sa.String(256)),
        sa.Column("contact_phone", sa.String(32)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("config", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_schools_code", "schools", ["code"], unique=True)

    # Step 2: Create grades table
    op.create_table(
        "grades",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("school_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"),
                  sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("grade_level", sa.Integer, nullable=False),
        sa.Column("academic_year", sa.String(16), nullable=False, server_default="2026-2027"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_grades_school", "grades", ["school_id", "grade_level"])

    # Step 3: Create subject_groups table
    op.create_table(
        "subject_groups",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("school_id", sa.BigInteger().with_variant(sa.Integer, "sqlite"),
                  sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(32), nullable=False),
        sa.Column("leader_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("member_ids", sa.JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subject_groups_school", "subject_groups", ["school_id", "subject"])

    # Step 4: Add school_id to 7 business tables
    _school_id_type = sa.BigInteger().with_variant(sa.Integer, "sqlite")
    _school_fk = sa.ForeignKey("schools.id", ondelete="RESTRICT")

    for table in ["users", "homeworks", "submissions", "grading_results", "corrections", "analytics_snapshots"]:
        op.add_column(table, sa.Column(
            "school_id", _school_id_type, _school_fk,
            nullable=False, server_default="1",
        ))

    # classes also gets school_id (it already has other columns)
    op.add_column("classes", sa.Column(
        "school_id", _school_id_type, _school_fk,
        nullable=False, server_default="1",
    ))

    # Step 5: Add grade_id/class_code/is_active to classes
    op.add_column("classes", sa.Column(
        "grade_id", _school_id_type,
        sa.ForeignKey("grades.id", ondelete="SET NULL"),
    ))
    op.add_column("classes", sa.Column("class_code", sa.String(32)))
    op.add_column("classes", sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")))

    # Add parent_of and pii_encrypted to users
    op.add_column("users", sa.Column("parent_of", sa.JSON, nullable=False, server_default=sa.text("'[]'")))
    op.add_column("users", sa.Column("pii_encrypted", sa.Text))

    # Add school_id to agent_trace (nullable, for audit — no RLS)
    op.add_column("agent_trace", sa.Column("school_id", _school_id_type, nullable=True))

    # Step 6: Insert default school
    op.execute(
        "INSERT INTO schools (id, name, code, school_type, is_active, config) "
        "VALUES (1, '默认学校', 'default', 'secondary', true, '{}') "
        "ON CONFLICT (id) DO NOTHING"
    )

    # Step 7: Backfill school_id=1 for existing rows
    # (All existing data belongs to the default school. The server_default='1'
    # already set the value during ALTER TABLE, but we run UPDATE explicitly
    # to handle any edge cases. This is a no-op for fresh installs.)
    for table in ["users", "classes", "homeworks", "submissions", "grading_results", "corrections", "analytics_snapshots"]:
        op.execute(f"UPDATE {table} SET school_id = 1 WHERE school_id IS NULL")

    # Step 8: Create indexes
    op.create_index("ix_users_school", "users", ["school_id"])
    op.create_index("ix_classes_school_grade", "classes", ["school_id", "grade_id"])
    op.create_index("ix_homeworks_school", "homeworks", ["school_id"])
    op.create_index("ix_submission_school", "submissions", ["school_id"])
    op.create_index("ix_grading_school", "grading_results", ["school_id"])
    op.create_index("ix_correction_school", "corrections", ["school_id"])
    op.create_index("ix_analytics_school", "analytics_snapshots", ["school_id"])

    # Step 9: Enable PG RLS (PG only — SQLite does not support RLS)
    _enable_rls()


def _enable_rls() -> None:
    """Enable Row-Level Security on all tables with school_id.

    Only runs on PostgreSQL (detected via dialect name). SQLite is skipped
    — tests use application-level school_id filtering instead.

    RLS covers 11 tables (all tables with school_id except agent_trace):
    users, classes, homeworks, submissions, grading_results,
    corrections, analytics_snapshots, grades, subject_groups.

    Note: schools table itself does NOT get RLS (it's the root tenant table).
    Sprint 6 tables (tenant_llm_config, llm_content_filter_log) will get
    their own RLS migration when they are created.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    rls_tables = [
        "users", "classes", "homeworks", "submissions",
        "grading_results", "corrections", "analytics_snapshots",
        "grades", "subject_groups",
    ]

    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

        # Tenant isolation: only see rows matching current tenant
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (school_id = current_setting('app.current_school_id', true)::bigint)"
        )

        # super_admin bypasses RLS
        op.execute(
            f"CREATE POLICY tenant_admin ON {table} FOR ALL "
            f"USING (current_setting('app.current_role', true) = 'super_admin' "
            f"OR school_id = current_setting('app.current_school_id', true)::bigint)"
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Drop RLS policies (PG only)
    if bind.dialect.name == "postgresql":
        rls_tables = [
            "users", "classes", "homeworks", "submissions",
            "grading_results", "corrections", "analytics_snapshots",
            "grades", "subject_groups",
        ]
        for table in rls_tables:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"DROP POLICY IF EXISTS tenant_admin ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop indexes
    for idx, table in [
        ("ix_analytics_school", "analytics_snapshots"),
        ("ix_correction_school", "corrections"),
        ("ix_grading_school", "grading_results"),
        ("ix_submission_school", "submissions"),
        ("ix_homeworks_school", "homeworks"),
        ("ix_classes_school_grade", "classes"),
        ("ix_users_school", "users"),
        ("ix_subject_groups_school", "subject_groups"),
        ("ix_grades_school", "grades"),
        ("ix_schools_code", "schools"),
    ]:
        op.drop_index(idx, table_name=table)

    # Drop columns from business tables
    for table in ["users", "classes", "homeworks", "submissions", "grading_results", "corrections", "analytics_snapshots"]:
        op.drop_column(table, "school_id")

    # Drop classes extra columns
    op.drop_column("classes", "is_active")
    op.drop_column("classes", "class_code")
    op.drop_column("classes", "grade_id")

    # Drop users extra columns
    op.drop_column("users", "pii_encrypted")
    op.drop_column("users", "parent_of")

    # Drop agent_trace school_id
    op.drop_column("agent_trace", "school_id")

    # Drop new tables
    op.drop_table("subject_groups")
    op.drop_table("grades")
    op.drop_table("schools")
