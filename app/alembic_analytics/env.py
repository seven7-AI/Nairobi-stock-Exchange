"""Alembic environment for the analytics store (``alembic -n analytics``).

Separate from ``app/alembic/env.py`` on purpose: that chain migrates the
Postgres platform tables, this one migrates the SQLite analytics file. The two
never share a revision graph.

* The URL comes from ``Settings.analytics_db_path`` unless the caller already
  set ``sqlalchemy.url`` on the config (tests and ``upgrade_analytics_db`` do,
  to target a temporary file).
* ``render_as_batch=True`` because SQLite cannot ALTER most things in place;
  batch mode rebuilds the table instead.

    codegraph explore "upgrade_analytics_db AnalyticsBase env.py"
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.web.config import get_settings

# Importing the package attaches every analytics table to the metadata.
from app.web.db.analytics.models import AnalyticsBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    from app.web.db.analytics.base import analytics_url

    config.set_main_option("sqlalchemy.url", analytics_url(get_settings().analytics_db_path))

target_metadata = AnalyticsBase.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the SQLite file."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
