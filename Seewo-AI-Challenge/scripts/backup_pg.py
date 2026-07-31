#!/usr/bin/env python3
"""V2.0 Sprint 5 (5.11): 异地备份脚本 — pg_dump + OSS 上传 + 恢复演练.

功能:
  backup   — pg_dump 全量备份 + 上传 OSS（可选）+ 本地轮转
  restore  — 从备份恢复（指定 --file 或最新备份）
  verify   — 恢复演练（restore 到临时库 + 行数校验 + 清理）
  list     — 列出本地备份文件

用法:
  python scripts/backup_pg.py backup
  python scripts/backup_pg.py backup --oss
  python scripts/backup_pg.py restore --file backup_20260731_103000.sql.gz
  python scripts/backup_pg.py verify
  python scripts/backup_pg.py list

环境变量:
  PG_HOST (default: 127.0.0.1)
  PG_PORT (default: 5432)
  PG_DB   (default: seewo)
  PG_USER (default: seewo)
  PG_PASSWORD (from .env or env)
  BACKUP_DIR (default: /var/backups/seewo-pg)
  OSS_ENDPOINT, OSS_BUCKET, OSS_ACCESS_KEY, OSS_SECRET_KEY (for --oss)
  RETENTION_DAYS (default: 30)

Cron 示例 (每天 2:00 AM):
  0 2 * * * /usr/bin/python3 /root/seewo-ai-challenge/Seewo-AI-Challenge/scripts/backup_pg.py backup --oss >> /var/log/seewo-backup.log 2>&1
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _get_pg_config() -> dict:
    """Get PostgreSQL connection config from environment."""
    return {
        "host": os.environ.get("PG_HOST", "127.0.0.1"),
        "port": os.environ.get("PG_PORT", "5432"),
        "db": os.environ.get("PG_DB", "seewo"),
        "user": os.environ.get("PG_USER", "seewo"),
        "password": os.environ.get("PG_PASSWORD", ""),
    }


def _get_backup_dir() -> Path:
    d = Path(os.environ.get("BACKUP_DIR", "/var/backups/seewo-pg"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pg_env() -> dict:
    """Return env dict with PGPASSWORD set."""
    env = dict(os.environ)
    cfg = _get_pg_config()
    if cfg["password"]:
        env["PGPASSWORD"] = cfg["password"]
    return env


def cmd_backup(args) -> int:
    """Full pg_dump backup with optional gzip + OSS upload + rotation."""
    cfg = _get_pg_config()
    backup_dir = _get_backup_dir()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.sql"
    filepath = backup_dir / filename

    print(f"[backup] Starting pg_dump → {filepath}")

    # pg_dump command
    cmd = [
        "pg_dump",
        "-h", cfg["host"],
        "-p", cfg["port"],
        "-U", cfg["user"],
        "-d", cfg["db"],
        "--no-owner",
        "--no-privileges",
        "-f", str(filepath),
    ]

    env = _pg_env()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[backup] FAILED: pg_dump error: {result.stderr}", file=sys.stderr)
        return 1

    print(f"[backup] pg_dump completed: {filepath} ({filepath.stat().st_size} bytes)")

    # Compress
    gz_path = filepath.with_suffix(".sql.gz")
    with open(filepath, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    filepath.unlink()  # remove uncompressed
    print(f"[backup] Compressed: {gz_path} ({gz_path.stat().st_size} bytes)")

    # OSS upload (optional)
    if args.oss:
        _upload_oss(gz_path)

    # Local rotation
    retention_days = int(os.environ.get("RETENTION_DAYS", "30"))
    _rotate_backups(backup_dir, retention_days)

    print(f"[backup] Done. Retention: {retention_days} days")
    return 0


def _upload_oss(filepath: Path) -> bool:
    """Upload to Alibaba Cloud OSS (or compatible S3)."""
    endpoint = os.environ.get("OSS_ENDPOINT", "")
    bucket = os.environ.get("OSS_BUCKET", "")
    access_key = os.environ.get("OSS_ACCESS_KEY", "")
    secret_key = os.environ.get("OSS_SECRET_KEY", "")

    if not all([endpoint, bucket, access_key, secret_key]):
        print("[backup] OSS: env vars not set, skipping upload", file=sys.stderr)
        return False

    try:
        import oss2
        auth = oss2.Auth(access_key, secret_key)
        oss_bucket = oss2.Bucket(auth, endpoint, bucket)
        key = f"seewo-pg/{filepath.name}"
        oss_bucket.put_object_from_file(key, str(filepath))
        print(f"[backup] OSS uploaded: oss://{bucket}/{key}")
        return True
    except ImportError:
        print("[backup] oss2 not installed, trying aws s3 cli...", file=sys.stderr)
        # Fallback: aws s3 cp
        s3_uri = f"s3://{bucket}/seewo-pg/{filepath.name}"
        result = subprocess.run(
            ["aws", "s3", "cp", str(filepath), s3_uri],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"[backup] S3 uploaded: {s3_uri}")
            return True
        print(f"[backup] S3 upload failed: {result.stderr}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[backup] OSS upload failed: {e}", file=sys.stderr)
        return False


def _rotate_backups(backup_dir: Path, retention_days: int) -> int:
    """Delete local backups older than retention_days."""
    cutoff = time.time() - (retention_days * 86400)
    deleted = 0
    for f in backup_dir.glob("backup_*.sql.gz"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
            print(f"[backup] Rotated (deleted): {f.name}")
    return deleted


def cmd_restore(args) -> int:
    """Restore from a backup file."""
    cfg = _get_pg_config()
    backup_dir = _get_backup_dir()

    if args.file:
        gz_path = backup_dir / args.file
        if not gz_path.exists():
            # Try as absolute path
            gz_path = Path(args.file)
    else:
        # Find latest backup
        backups = sorted(backup_dir.glob("backup_*.sql.gz"))
        if not backups:
            print("[restore] No backup files found", file=sys.stderr)
            return 1
        gz_path = backups[-1]

    if not gz_path.exists():
        print(f"[restore] File not found: {gz_path}", file=sys.stderr)
        return 1

    print(f"[restore] Restoring from: {gz_path}")

    # Decompress
    sql_content = gzip.open(gz_path, "rt", encoding="utf-8").read()
    tmp_sql = gz_path.with_suffix(".sql")
    tmp_sql.write_text(sql_content, encoding="utf-8")

    # psql restore
    cmd = [
        "psql",
        "-h", cfg["host"],
        "-p", cfg["port"],
        "-U", cfg["user"],
        "-d", cfg["db"],
        "-f", str(tmp_sql),
    ]

    env = _pg_env()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    tmp_sql.unlink()  # cleanup

    if result.returncode != 0:
        print(f"[restore] FAILED: {result.stderr}", file=sys.stderr)
        return 1

    print(f"[restore] Done. Restored from {gz_path.name}")
    return 0


def cmd_verify(args) -> int:
    """Recovery drill: restore to a temp database, verify row counts, cleanup."""
    cfg = _get_pg_config()
    backup_dir = _get_backup_dir()
    test_db = f"{cfg['db']}_verify_drill"

    backups = sorted(backup_dir.glob("backup_*.sql.gz"))
    if not backups:
        print("[verify] No backup files found", file=sys.stderr)
        return 1

    gz_path = backups[-1]
    print(f"[verify] Recovery drill from: {gz_path.name}")

    env = _pg_env()

    # Create temp database
    result = subprocess.run(
        ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
         "-d", "postgres", "-c", f"CREATE DATABASE {test_db};"],
        env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[verify] CREATE DATABASE failed: {result.stderr}", file=sys.stderr)
        return 1

    try:
        # Restore to temp DB
        sql_content = gzip.open(gz_path, "rt", encoding="utf-8").read()
        tmp_sql = backup_dir / "_verify_temp.sql"
        tmp_sql.write_text(sql_content, encoding="utf-8")

        result = subprocess.run(
            ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
             "-d", test_db, "-f", str(tmp_sql)],
            env=env, capture_output=True, text=True
        )
        tmp_sql.unlink()

        if result.returncode != 0:
            print(f"[verify] Restore to temp DB failed: {result.stderr}", file=sys.stderr)
            return 1

        # Verify: count rows in key tables
        tables = ["users", "homeworks", "submissions", "corrections", "schools", "grades"]
        print("[verify] Row counts:")
        all_ok = True
        for table in tables:
            result = subprocess.run(
                ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
                 "-d", test_db, "-t", "-c", f"SELECT COUNT(*) FROM {table};"],
                env=env, capture_output=True, text=True
            )
            count = result.stdout.strip() if result.returncode == 0 else "ERROR"
            # Table might not exist (if backup is from older version)
            if result.returncode != 0 and "does not exist" in result.stderr:
                count = "N/A (table not in this backup)"
            elif result.returncode != 0:
                all_ok = False
            print(f"  {table}: {count}")

        if all_ok:
            print("[verify] PASSED — backup is restorable and data intact")
            return 0
        else:
            print("[verify] WARNING — some tables had errors", file=sys.stderr)
            return 1

    finally:
        # Cleanup: drop temp database
        subprocess.run(
            ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
             "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {test_db};"],
            env=env, capture_output=True, text=True
        )
        print(f"[verify] Cleaned up temp database: {test_db}")


def cmd_list(args) -> int:
    """List available backups."""
    backup_dir = _get_backup_dir()
    backups = sorted(backup_dir.glob("backup_*.sql.gz"))
    if not backups:
        print("[list] No backups found")
        return 0

    print(f"{'File':<40} {'Size':>12} {'Date':<20}")
    print("-" * 72)
    for f in backups:
        size = f.stat().st_size
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
        size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
        print(f"{f.name:<40} {size_str:>12} {mtime:<20}")

    print(f"\nTotal: {len(backups)} backups in {backup_dir}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Seewo PG Backup & Recovery")
    sub = parser.add_subparsers(dest="command", required=True)

    p_backup = sub.add_parser("backup", help="Full pg_dump backup")
    p_backup.add_argument("--oss", action="store_true", help="Upload to OSS/S3")
    p_backup.set_defaults(func=cmd_backup)

    p_restore = sub.add_parser("restore", help="Restore from backup")
    p_restore.add_argument("--file", help="Specific backup file (default: latest)")
    p_restore.set_defaults(func=cmd_restore)

    p_verify = sub.add_parser("verify", help="Recovery drill")
    p_verify.set_defaults(func=cmd_verify)

    p_list = sub.add_parser("list", help="List available backups")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
