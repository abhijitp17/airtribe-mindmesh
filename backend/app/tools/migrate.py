"""Bring a database up to date: Alembic migrations, then row-level security (sql/rls.sql).

    python -m app.tools.migrate

Run it as the role that owns the tables (in docker compose: mindmesh_app, the API's own role)
before starting the API; the compose `migrate` service does this on every deploy. Both steps
are idempotent. On SQLite (dev) only the migrations run: RLS is a Postgres feature.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[2]


def main() -> int:
    from alembic import command
    from alembic.config import Config

    from ..config import get_settings
    from ..db import engine

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")
    if not get_settings().database_url.startswith("postgresql"):
        print("migrations applied (not Postgres: row-level security skipped)")
        return 0
    with engine.begin() as conn:
        # Raw driver call with no parameters: the script's format('%I', ...) must not be read as placeholders.
        conn.connection.driver_connection.execute((BACKEND / "sql" / "rls.sql").read_text())
        n = conn.execute(text(
            "SELECT count(*) FROM pg_class WHERE relkind = 'r' AND relnamespace = current_schema()::regnamespace "
            "AND relrowsecurity AND relforcerowsecurity")).scalar()
    print(f"migrations applied; row-level security enabled and forced on {n} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
