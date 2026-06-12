"""Alembic 环境:DSN 与 target_metadata 都从应用 config 注入(env 可覆盖)。"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from pipeline.config import load_config
from pipeline.index.pg_models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 连接串来自 config/settings.toml(或 env PIPELINE_DB_DSN),不在 alembic.ini 明文存
config.set_main_option("sqlalchemy.url", load_config().db.dsn)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
