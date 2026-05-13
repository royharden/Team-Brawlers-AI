"""Alembic env — master plan §5.

Wires Alembic to `agentforge.memory.models.Base.metadata` and pulls the DB
URL from `MainConfig.platform_db_url` so dev/CI/prod all read the same
canonical setting. Supports both `offline` and `online` migration modes.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from agentforge.config import get_settings
from agentforge.memory.db import _ensure_sqlite_parent_dir
from agentforge.memory.models import Base

# Alembic config object — values from `alembic.ini`.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pull the canonical DB URL out of platform settings (single source of truth).
_settings_url = get_settings().platform_db_url
config.set_main_option("sqlalchemy.url", _settings_url)
_ensure_sqlite_parent_dir(_settings_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without a live engine."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url is not None and url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect to the DB and apply."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
