#!/usr/bin/env bash
# initdb.sh — PG 容器首次启动时执行
# 唯一入口：alembic upgrade head
# 注意：schema.sql 已删除（P0-3 修复），所有 DDL 由 alembic 唯一负责
set -euo pipefail

echo "[initdb] $(date -Iseconds) starting alembic upgrade head"
alembic -c /app/infra/pg/alembic.ini upgrade head
echo "[initdb] $(date -Iseconds) alembic upgrade head completed"
