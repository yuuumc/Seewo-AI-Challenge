"""Alembic 配置：使用 sync DSN（psycopg2）跑迁移.

即使主应用用 asyncpg，迁移工具仍用同步驱动更稳。
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

# 从环境变量覆盖 DSN
if os.getenv("DATABASE_URL_SYNC"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL_SYNC"])

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 留空：不使用 autogenerate 的 target_metadata，由具体 migration 文件手写 DDL
target_metadata = None


def run_migrations_offline() -> None:
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
