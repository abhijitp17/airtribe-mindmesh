"""Alembic environment: uses the app's engine/URL (DATABASE_URL) and full model metadata."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.db import Base, engine, load_all_models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_all_models()  # registers every app/models*.py table (incl. models_jobs -> jobs)
target_metadata = Base.metadata
_is_sqlite = engine.dialect.name == "sqlite"


def run_migrations_offline() -> None:
    context.configure(
        url=engine.url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=_is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_is_sqlite,  # SQLite needs batch mode for ALTER
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
