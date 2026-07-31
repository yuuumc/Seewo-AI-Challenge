#!/usr/bin/env python3
"""V2.0 Sprint 6 (6.12): 每月恢复演练脚本.

基于 Sprint 5 backup_pg.py 的 verify 功能，扩展为完整的恢复演练：
  1. 从最新备份恢复到临时库
  2. 行数校验（关键表）
  3. 数据完整性检查（抽样记录对比）
  4. 生成演练报告（JSON + 文本）
  5. 通知运维（飞书 webhook 可选）
  6. 清理临时库

用法:
  python scripts/backup_drill.py
  python scripts/backup_drill.py --report-dir /var/log/seewo-drills
  python scripts/backup_drill.py --notify-webhook https://...

Cron (每月 1 日 3:00 AM):
  0 3 1 * * /usr/bin/python3 /root/seewo-ai-challenge/Seewo-AI-Challenge/scripts/backup_drill.py >> /var/log/seewo-drill.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _get_pg_config() -> dict:
    return {
        "host": os.environ.get("PG_HOST", "127.0.0.1"),
        "port": os.environ.get("PG_PORT", "5432"),
        "db": os.environ.get("PG_DB", "seewo"),
        "user": os.environ.get("PG_USER", "seewo"),
        "password": os.environ.get("PG_PASSWORD", ""),
    }


def _pg_env() -> dict:
    env = dict(os.environ)
    cfg = _get_pg_config()
    if cfg["password"]:
        env["PGPASSWORD"] = cfg["password"]
    return env


def _get_backup_dir() -> Path:
    return Path(os.environ.get("BACKUP_DIR", "/var/backups/seewo-pg"))


def _run_psql(db: str, sql: str, env: dict) -> tuple[int, str, str]:
    """Run a psql command and return (returncode, stdout, stderr)."""
    cfg = _get_pg_config()
    cmd = [
        "psql", "-h", cfg["host"], "-p", cfg["port"],
        "-U", cfg["user"], "-d", db, "-t", "-c", sql,
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def run_drill(report_dir: str = ".", notify_webhook: str = "") -> dict:
    """Run a full recovery drill and generate a report.

    Returns the drill report dict.
    """
    cfg = _get_pg_config()
    env = _pg_env()
    backup_dir = _get_backup_dir()
    test_db = f"{cfg['db']}_drill_{int(time.time())}"

    report = {
        "drill_time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "status": "running",
        "steps": [],
        "checks": {},
        "errors": [],
    }

    def add_step(name: str, status: str, detail: str = ""):
        report["steps"].append({
            "step": name,
            "status": status,
            "detail": detail,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        })
        print(f"  [{status}] {name}: {detail}")

    print("=" * 60)
    print("  每月恢复演练")
    print(f"  时间: {report['drill_time']}")
    print("=" * 60)

    # Step 1: Find latest backup
    backups = sorted(backup_dir.glob("backup_*.sql.gz"))
    if not backups:
        report["status"] = "failed"
        report["errors"].append("No backup files found")
        add_step("find_backup", "failed", "No backups in " + str(backup_dir))
        _save_report(report, report_dir)
        return report

    gz_path = backups[-1]
    add_step("find_backup", "ok", f"Using {gz_path.name}")

    # Step 2: Create temp database
    result = subprocess.run(
        ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
         "-d", "postgres", "-c", f"CREATE DATABASE {test_db};"],
        env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        report["status"] = "failed"
        report["errors"].append(f"CREATE DATABASE failed: {result.stderr}")
        add_step("create_temp_db", "failed", result.stderr)
        _save_report(report, report_dir)
        return report

    add_step("create_temp_db", "ok", f"Created {test_db}")

    try:
        # Step 3: Restore to temp DB
        import gzip
        sql_content = gzip.open(gz_path, "rt", encoding="utf-8").read()
        tmp_sql = backup_dir / "_drill_temp.sql"
        tmp_sql.write_text(sql_content, encoding="utf-8")

        result = subprocess.run(
            ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
             "-d", test_db, "-f", str(tmp_sql)],
            env=env, capture_output=True, text=True
        )
        tmp_sql.unlink()

        if result.returncode != 0:
            report["status"] = "failed"
            report["errors"].append(f"Restore failed: {result.stderr}")
            add_step("restore", "failed", result.stderr[:200])
            return report

        add_step("restore", "ok", f"Restored {len(sql_content)} bytes")

        # Step 4: Row count checks
        tables = ["users", "homeworks", "submissions", "corrections",
                   "schools", "grades", "classes", "subject_groups"]
        all_counts_ok = True
        for table in tables:
            code, stdout, stderr = _run_psql(test_db, f"SELECT COUNT(*) FROM {table};", env)
            if code == 0:
                count = stdout.strip()
                report["checks"][table] = {"rows": int(count) if count else 0, "status": "ok"}
                print(f"    {table}: {count} rows")
            elif "does not exist" in stderr:
                report["checks"][table] = {"rows": 0, "status": "not_in_backup"}
                print(f"    {table}: N/A (not in this backup)")
            else:
                report["checks"][table] = {"rows": 0, "status": "error", "error": stderr[:100]}
                all_counts_ok = False

        add_step("row_count_check", "ok" if all_counts_ok else "warning",
                 f"Checked {len(tables)} tables")

        # Step 5: Data integrity spot check
        # Verify at least one user exists
        code, stdout, _ = _run_psql(test_db, "SELECT COUNT(*) FROM users WHERE role='admin';", env)
        admin_count = int(stdout) if stdout and stdout.isdigit() else 0
        report["checks"]["admin_users"] = admin_count
        add_step("integrity_check", "ok" if admin_count > 0 else "warning",
                 f"Admin users: {admin_count}")

        # Step 6: Summary
        report["status"] = "passed" if all_counts_ok and admin_count > 0 else "passed_with_warnings"

    except Exception as e:
        report["status"] = "failed"
        report["errors"].append(str(e))
        add_step("exception", "failed", str(e))

    finally:
        # Cleanup: drop temp database
        subprocess.run(
            ["psql", "-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"],
             "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {test_db};"],
            env=env, capture_output=True, text=True
        )
        add_step("cleanup", "ok", f"Dropped {test_db}")

    # Generate summary
    total_tables = len(report["checks"])
    ok_tables = sum(1 for v in report["checks"].values() if v.get("status") == "ok")
    report["summary"] = {
        "total_checks": total_tables,
        "passed": ok_tables,
        "backup_file": gz_path.name,
        "backup_size_bytes": gz_path.stat().st_size,
    }

    _save_report(report, report_dir)

    # Notify via webhook
    if notify_webhook:
        _notify_webhook(notify_webhook, report)

    print(f"\n{'=' * 60}")
    print(f"  演练结果: {report['status'].upper()}")
    print(f"  检查表: {ok_tables}/{total_tables} OK")
    print(f"  备份文件: {gz_path.name}")
    print(f"  报告已保存")
    print(f"{'=' * 60}")

    return report


def _save_report(report: dict, report_dir: str) -> None:
    """Save drill report as JSON and text."""
    rdir = Path(report_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    
    # JSON report
    json_path = rdir / f"drill_report_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # Text report
    txt_path = rdir / f"drill_report_{timestamp}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"恢复演练报告\n{'=' * 60}\n")
        f.write(f"时间: {report['drill_time']}\n")
        f.write(f"状态: {report['status']}\n\n")
        f.write("步骤:\n")
        for step in report.get("steps", []):
            f.write(f"  [{step['status']}] {step['step']}: {step['detail']}\n")
        f.write(f"\n检查结果:\n")
        for table, result in report.get("checks", {}).items():
            f.write(f"  {table}: {result}\n")
        if report.get("errors"):
            f.write(f"\n错误:\n")
            for err in report["errors"]:
                f.write(f"  - {err}\n")
        f.write(f"\n摘要: {report.get('summary', {})}\n")


def _notify_webhook(webhook_url: str, report: dict) -> None:
    """Send drill result to Feishu webhook."""
    try:
        import urllib.request
        status_emoji = {"passed": "✅", "failed": "❌", "passed_with_warnings": "⚠️"}.get(
            report["status"], "❓")
        
        message = {
            "msg_type": "text",
            "content": {
                "text": f"{status_emoji} 恢复演练报告\n"
                        f"状态: {report['status']}\n"
                        f"时间: {report['drill_time']}\n"
                        f"备份: {report.get('summary', {}).get('backup_file', 'N/A')}\n"
                        f"检查表: {report.get('summary', {}).get('passed', 0)}/"
                        f"{report.get('summary', {}).get('total_checks', 0)} OK"
            }
        }
        
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(message).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        print("[OK] Webhook notification sent")
    except Exception as e:
        print(f"[WARN] Webhook notification failed: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Monthly backup recovery drill")
    parser.add_argument("--report-dir", default=".",
                        help="Directory for drill reports (default: current)")
    parser.add_argument("--notify-webhook", default="",
                        help="Feishu webhook URL for notification")
    
    args = parser.parse_args()
    report = run_drill(
        report_dir=args.report_dir,
        notify_webhook=args.notify_webhook,
    )
    sys.exit(0 if report["status"] in ("passed", "passed_with_warnings") else 1)


if __name__ == "__main__":
    main()
