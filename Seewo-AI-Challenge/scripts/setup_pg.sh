#!/bin/bash
# V1.0 Sprint 2: PG deployment one-shot script (dev/local).
# Usage: bash scripts/setup_pg.sh [--skip-migration]
#
# Starts PostgreSQL via docker-compose (with dev port override for localhost access),
# runs Alembic migrations, migrates JSON demo data into PG, and verifies db_store.
#
# Prerequisites:
#   - Docker + docker-compose installed
#   - pip install sqlalchemy psycopg2-binary alembic bcrypt
#
# Steps:
#   1. Start PostgreSQL via docker-compose (+ dev override for port 5432)
#   2. Wait for PG to be ready (pg_isready, 30 retries)
#   3. Run Alembic migration (0001 + 0002) or create_all fallback
#   4. Run JSON → PG migration script
#   5. Verify db_store connects to PG and can read users

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

SKIP_MIGRATION=false
if [[ "${1:-}" == "--skip-migration" ]]; then
    SKIP_MIGRATION=true
fi

PG_URL="postgresql+psycopg2://seewo:seewo@localhost:5432/seewo"

echo "=========================================="
echo "  V1.0 PG Deployment — Seewo AI Challenge"
echo "=========================================="
echo "  Repo: $REPO_ROOT"
echo ""

# ── Step 1: Start PostgreSQL ──
echo "[1/5] Starting PostgreSQL via docker-compose..."
if ! command -v docker &>/dev/null; then
    echo "  ERROR: docker not found. Install Docker first."
    exit 1
fi

if docker compose version &>/dev/null; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC="docker-compose"
else
    echo "  ERROR: neither 'docker compose' nor 'docker-compose' found."
    exit 1
fi

# Use dev override to expose port 5432 on localhost
$DC -f docker-compose.yml -f docker-compose.dev.yml up -d postgres
echo "  PostgreSQL container started (port 5432 exposed via dev override)."

# ── Step 2: Wait for PG readiness ──
echo ""
echo "[2/5] Waiting for PostgreSQL to be ready..."
MAX_RETRIES=30
for i in $(seq 1 $MAX_RETRIES); do
    if $DC -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres pg_isready -U seewo -d seewo &>/dev/null; then
        echo "  PostgreSQL is ready (attempt $i)."
        break
    fi
    if [[ $i -eq $MAX_RETRIES ]]; then
        echo "  ERROR: PostgreSQL not ready after $MAX_RETRIES attempts."
        exit 1
    fi
    sleep 2
done

# ── Step 3: Run Alembic migration ──
if [[ "$SKIP_MIGRATION" == "false" ]]; then
    echo ""
    echo "[3/5] Running Alembic migrations..."
    export DATABASE_URL_SYNC="$PG_URL"

    if command -v alembic &>/dev/null; then
        alembic -c infra/pg/alembic.ini upgrade head
    elif python3 -m alembic --version &>/dev/null 2>&1; then
        python3 -m alembic -c infra/pg/alembic.ini upgrade head
    else
        echo "  WARN: alembic not installed, using create_all fallback."
        python3 -c "
import sys; sys.path.insert(0, '.')
from infra.pg.orm import Base
from sqlalchemy import create_engine
engine = create_engine('$PG_URL')
Base.metadata.create_all(engine)
print('  Tables created via create_all.')
"
    fi
    echo "  Migrations applied."
else
    echo ""
    echo "[3/5] Skipping migration (--skip-migration)."
fi

# ── Step 4: Run JSON → PG migration ──
echo ""
echo "[4/5] Running JSON → PG data migration..."
export DATABASE_URL_SYNC="$PG_URL"
python3 scripts/migrate_json_to_pg.py \
    --db-url "$PG_URL" \
    --data-dir demo/data
echo "  Data migration complete."

# ── Step 5: Verify db_store ──
echo ""
echo "[5/5] Verifying db_store connects to PG..."
python3 -c "
import sys, os
sys.path.insert(0, '.')
sys.path.insert(0, 'demo')
os.environ['DATABASE_URL_SYNC'] = '$PG_URL'
import db_store
db_store.reset_pg_cache()
if db_store.is_pg_available():
    user = db_store.get_user('teacher')
    if user:
        print(f'  OK: db_store -> PG, user=teacher found (role={user[\"role\"]})')
    else:
        print('  WARN: PG connected but teacher user not found.')
else:
    print('  ERROR: db_store cannot connect to PG.')
    exit 1
"

echo ""
echo "=========================================="
echo "  PG deployment complete!"
echo "  - PostgreSQL: localhost:5432/seewo"
echo "  - Tables: 8 (users, classes, homeworks, submissions,"
echo "    grading_results, corrections, analytics_snapshots, agent_trace)"
echo "  - Data: migrated from demo/data/*.json"
echo "  - db_store: PG-backed (no DEMO_USERS fallback needed)"
echo "=========================================="
