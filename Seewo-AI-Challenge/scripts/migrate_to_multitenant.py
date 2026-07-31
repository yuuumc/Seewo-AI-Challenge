#!/usr/bin/env python3
"""V2.0 Sprint 5: Multi-tenant migration script.

Migrates existing V1.5 data (JSON files + PG) to the V2.0 multi-tenant schema.
All existing data is assigned to school_id=1 (default school).

This script handles DATA only — DDL (table creation, column addition, RLS)
is done by Alembic migration 0004. This script does NOT duplicate DDL.

Usage:
    python scripts/migrate_to_multitenant.py --dry-run          # Preview
    python scripts/migrate_to_multitenant.py --school-id 1      # Specify default school
    python scripts/migrate_to_multitenant.py --skip-rls          # Skip RLS (SQLite)
    python scripts/migrate_to_multitenant.py --json-sync         # Sync JSON → PG
    python scripts/migrate_to_multitenant.py --verify            # Verify migration
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure demo/ is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

_REPO_ROOT = _DEMO_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_RLS_TABLES = [
    "users", "classes", "homeworks", "submissions",
    "grading_results", "corrections", "analytics_snapshots",
    "grades", "subject_groups",
]


def _load_json(name: str) -> dict:
    """Load a JSON data file from demo/data/."""
    path = _DEMO_DIR / "data" / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get_pg_engine():
    """Get PG engine if available."""
    db_url = os.environ.get("DATABASE_URL", "") or os.environ.get("DATABASE_URL_SYNC", "")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine, text
        return create_engine(db_url), text
    except Exception:
        return None


def check_prerequisites(dry_run: bool = False) -> bool:
    """Step 1: Verify Alembic 0004 has been executed."""
    print("=== Step 1: Prerequisites check ===")
    result = _get_pg_engine()
    if result is None:
        print("  [SKIP] PG not available (SQLite/test mode)")
        return True

    engine, text = result
    with engine.connect() as conn:
        # Check schools table exists
        exists = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'schools')"
        )).scalar()
        if not exists:
            print("  [FAIL] schools table does not exist — run `alembic upgrade head` first")
            return False
        print("  [OK] schools table exists")

        # Check school_id columns exist on business tables
        for table in ["users", "classes", "homeworks", "submissions"]:
            exists = conn.execute(text(
                f"SELECT EXISTS (SELECT FROM information_schema.columns "
                f"WHERE table_name='{table}' AND column_name='school_id')"
            )).scalar()
            if not exists:
                print(f"  [FAIL] {table}.school_id column missing — run alembic 0004 first")
                return False
        print("  [OK] school_id columns present on business tables")

    # Print data summary
    _print_data_summary()
    return True


def _print_data_summary():
    """Print current data volume."""
    print("\n  Data summary:")
    # JSON files
    for name in ["students.json", "answers.json", "corrections.json", "questions.json"]:
        data = _load_json(name)
        if name == "students.json" and "students" in data:
            print(f"    {name}: {len(data['students'])} students")
        elif name == "questions.json" and "assignments" in data:
            print(f"    {name}: {len(data['assignments'])} assignments")
        elif name == "answers.json":
            count = sum(len(v) for v in data.values()) if isinstance(data, dict) else len(data)
            print(f"    {name}: {count} answers")
        elif name == "corrections.json":
            count = sum(len(v.get("corrections", [])) for v in data.values()) if isinstance(data, dict) else len(data)
            print(f"    {name}: {count} corrections")


def create_default_school(school_id: int = 1, dry_run: bool = False) -> bool:
    """Step 2: Ensure default school record exists."""
    print(f"\n=== Step 2: Create default school (id={school_id}) ===")
    if dry_run:
        print(f"  [DRY-RUN] Would INSERT INTO schools (id={school_id}, name='默认学校', code='default')")
        return True

    result = _get_pg_engine()
    if result is None:
        print("  [SKIP] PG not available")
        return True

    engine, text = result
    with engine.begin() as conn:
        conn.execute(text(
            f"INSERT INTO schools (id, name, code, school_type, is_active, config) "
            f"VALUES ({school_id}, '默认学校', 'default', 'secondary', true, '{{}}') "
            f"ON CONFLICT (id) DO NOTHING"
        ))
    print(f"  [OK] Default school ensured (id={school_id})")
    return True


def backfill_school_id(school_id: int = 1, dry_run: bool = False) -> bool:
    """Steps 3-9: Backfill school_id for all business tables."""
    print(f"\n=== Steps 3-9: Backfill school_id={school_id} ===")

    if dry_run:
        tables = ["users", "classes", "homeworks", "submissions", "grading_results", "corrections", "analytics_snapshots"]
        for table in tables:
            print(f"  [DRY-RUN] Would UPDATE {table} SET school_id={school_id} WHERE school_id IS NULL")
        return True

    result = _get_pg_engine()
    if result is None:
        print("  [SKIP] PG not available (JSON data stays in JSON files)")
        return True

    engine, text = result
    with engine.begin() as conn:
        # Direct tables: school_id = school_id (all same school)
        for table in ["users", "classes", "homeworks"]:
            result = conn.execute(text(
                f"UPDATE {table} SET school_id = {school_id} WHERE school_id IS NULL"
            ))
            print(f"  [OK] {table}: {result.rowcount} rows updated")

        # FK tables: backfill via student_id → users.school_id
        for table in ["submissions", "grading_results", "corrections", "analytics_snapshots"]:
            result = conn.execute(text(
                f"UPDATE {table} SET school_id = ("
                f"SELECT u.school_id FROM users u WHERE u.id = {table}.student_id) "
                f"WHERE {table}.school_id IS NULL"
            ))
            print(f"  [OK] {table}: {result.rowcount} rows updated")

    return True


def sync_json_to_pg(school_id: int = 1, dry_run: bool = False) -> bool:
    """Step 10: Sync JSON data to PG (optional, --json-sync flag)."""
    print(f"\n=== Step 10: JSON → PG sync (school_id={school_id}) ===")
    if dry_run:
        print("  [DRY-RUN] Would sync students.json, answers.json, corrections.json to PG")
        return True

    result = _get_pg_engine()
    if result is None:
        print("  [SKIP] PG not available")
        return True

    # Import db_store which handles JSON → PG sync
    try:
        from db_store import sync_all_json_to_pg
        sync_all_json_to_pg(school_id=school_id)
        print("  [OK] JSON data synced to PG")
    except ImportError:
        print("  [SKIP] db_store module not available")
    except Exception as e:
        print(f"  [WARN] JSON sync error: {e}")
    return True


def enable_rls(dry_run: bool = False, skip_rls: bool = False) -> bool:
    """Step 11: Enable RLS (PG only, --skip-rls for SQLite)."""
    print("\n=== Step 11: RLS (already handled by Alembic 0004) ===")
    if skip_rls:
        print("  [SKIP] --skip-rls flag set")
        return True

    result = _get_pg_engine()
    if result is None:
        print("  [SKIP] PG not available (SQLite does not support RLS)")
        return True

    engine, text = result
    if engine.dialect.name != "postgresql":
        print(f"  [SKIP] RLS not supported on {engine.dialect.name}")
        return True

    # RLS was already created by Alembic 0004 migration. We just verify it's active.
    with engine.connect() as conn:
        for table in _RLS_TABLES:
            result = conn.execute(text(
                f"SELECT relrowsecurity FROM pg_class WHERE relname = '{table}'"
            )).scalar()
            if result:
                print(f"  [OK] {table}: RLS enabled")
            else:
                print(f"  [WARN] {table}: RLS not enabled")
    return True


def verify_migration(school_id: int = 1) -> bool:
    """Step 12: Verify migration completeness."""
    print("\n=== Step 12: Verification ===")
    all_ok = True

    result = _get_pg_engine()
    if result is None:
        print("  [SKIP] PG not available — running JSON-only checks")
        # Verify JSON data is intact
        for name in ["students.json", "answers.json", "corrections.json"]:
            data = _load_json(name)
            if data:
                print(f"  [OK] {name}: present and readable")
            else:
                print(f"  [WARN] {name}: not found or empty")
        return True

    engine, text = result
    with engine.connect() as conn:
        # 1. Table structure
        for table in ["schools", "grades", "subject_groups"]:
            exists = conn.execute(text(
                f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name='{table}')"
            )).scalar()
            status = "[OK]" if exists else "[FAIL]"
            if not exists:
                all_ok = False
            print(f"  {status} Table {table} exists")

        # 2. school_id non-NULL on business tables
        for table in ["users", "classes", "homeworks", "submissions", "grading_results", "corrections", "analytics_snapshots"]:
            null_count = conn.execute(text(
                f"SELECT COUNT(*) FROM {table} WHERE school_id IS NULL"
            )).scalar()
            status = "[OK]" if null_count == 0 else "[FAIL]"
            if null_count > 0:
                all_ok = False
            print(f"  {status} {table}: {null_count} rows with NULL school_id")

        # 3. Default school exists
        count = conn.execute(text(
            f"SELECT COUNT(*) FROM schools WHERE id = {school_id}"
        )).scalar()
        status = "[OK]" if count > 0 else "[FAIL]"
        if count == 0:
            all_ok = False
        print(f"  {status} Default school (id={school_id}) exists")

        # 4. RLS enabled (PG only)
        if engine.dialect.name == "postgresql":
            for table in _RLS_TABLES:
                rls = conn.execute(text(
                    f"SELECT relrowsecurity FROM pg_class WHERE relname = '{table}'"
                )).scalar()
                status = "[OK]" if rls else "[WARN]"
                print(f"  {status} {table}: RLS {'enabled' if rls else 'NOT enabled'}")

    print(f"\n{'✅ All checks passed' if all_ok else '❌ Some checks failed'}")
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="V2.0 Multi-tenant migration")
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    parser.add_argument("--school-id", type=int, default=1, help="Default school ID")
    parser.add_argument("--skip-rls", action="store_true", help="Skip RLS (SQLite)")
    parser.add_argument("--json-sync", action="store_true", help="Sync JSON → PG")
    parser.add_argument("--verify", action="store_true", help="Verify migration only")
    args = parser.parse_args()

    if args.verify:
        ok = verify_migration(args.school_id)
        sys.exit(0 if ok else 1)

    print("=" * 60)
    print("V2.0 Multi-tenant Migration")
    print(f"  Mode: {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    print(f"  School ID: {args.school_id}")
    print(f"  Skip RLS: {args.skip_rls}")
    print(f"  JSON Sync: {args.json_sync}")
    print("=" * 60)

    steps = [
        ("Prerequisites", lambda: check_prerequisites(args.dry_run)),
        ("Create default school", lambda: create_default_school(args.school_id, args.dry_run)),
        ("Backfill school_id", lambda: backfill_school_id(args.school_id, args.dry_run)),
    ]

    if args.json_sync:
        steps.append(("JSON → PG sync", lambda: sync_json_to_pg(args.school_id, args.dry_run)))

    steps.append(("RLS verification", lambda: enable_rls(args.dry_run, args.skip_rls)))

    all_ok = True
    for name, step_fn in steps:
        if not step_fn():
            all_ok = False
            print(f"\n❌ Step failed: {name}")
            break

    # Always run verification
    if not args.dry_run:
        verify_migration(args.school_id)

    print("\n" + "=" * 60)
    if all_ok:
        print("✅ Migration completed successfully")
    else:
        print("❌ Migration completed with errors")
    print("=" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
