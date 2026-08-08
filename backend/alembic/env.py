"""Alembic environment. See architecture-plan §1 (SQLAlchemy/Alembic), §7.1 (DATABASE_PATH)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.db import models  # noqa: F401 - import populates Base.metadata for autogenerate
from app.db.base import Base, UTCDateTime
from app.db.session import sqlite_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", sqlite_url(get_settings().database_path))

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render `UTCDateTime` columns with a clean import instead of a fully-qualified inline reference.

    Without this, autogenerate emits `app.db.base.UTCDateTime(timezone=True)` with no
    corresponding import - broken on two counts (missing import, and an argument the
    custom type's constructor doesn't originally have been written to expect).
    """
    if type_ == "type" and isinstance(obj, UTCDateTime):
        autogen_context.imports.add("from app.db.base import UTCDateTime")  # type: ignore[attr-defined]
        return "UTCDateTime()"
    return False


def run_migrations_offline() -> None:
    """Emit SQL scripts against a URL, without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite can't ALTER most columns in place - see run_migrations_online
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite has no native ALTER TABLE for most operations; batch mode has Alembic
            # recreate the table under the hood instead. Needed from the first migration
            # since every later stage will alter these tables.
            render_as_batch=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
