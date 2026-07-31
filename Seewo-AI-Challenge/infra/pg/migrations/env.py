"""Alembic env — sync engine (Sprint 4 fix).

Uses the sync DSN (psycopg2) so ``alembic upgrade head`` works with
``DATABASE_URL_SYNC`` without needing asyncpg event loop.

The ``sqlalchemy.url`` is resolved in this order:
  1. ``DATABASE_URL_SYNC`` env var (preferred — set by docker-compose)
  2. ``DATABASE_URL`` env var (asyncpg suffix stripped)
  3. ``alembic.ini`` ``sqlalchemy.url`` fallback
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

# Resolve DSN from environment (overrides alembic.ini)
_sync_url = (
    os.environ.get("DATABASE_URL_SYNC")
    or os.environ.get("DATABASE_URL", "").replace("+asyncpg", "+psycopg2")
)
if _sync_url:
    config.set_main_option("sqlalchemy.url", _sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import ORM Base so autogenerate can detect models
try:
    from infra.pg.orm import Base
    target_metadata = Base.metadata
except ImportError:
    target_metadata = None


def run_migrations_offline() -> None:
    """Offline mode: generate SQL scripts without connecting to DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode: connect to DB and run migrations (sync engine)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
