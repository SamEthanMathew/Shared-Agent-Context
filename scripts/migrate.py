"""Bring the database to the current schema, safely, on every boot.

Three cases have to work:

1. **Fresh database** — nothing exists. Run every migration from scratch.
2. **Already managed by Alembic** — an ``alembic_version`` row exists. Upgrade
   to head; a no-op when already current.
3. **Pre-Alembic database** — the V1 deployment built its schema with
   ``metadata.create_all`` and was never stamped, so it has the 0001 tables but
   no version row. Running ``upgrade head`` here would try to re-create existing
   tables and fail. Stamp it at 0001 first, then upgrade.

Idempotent, so it is safe to run on every start.
"""
from __future__ import annotations

import os
import sys

# Runs as `python scripts/migrate.py`, so the repo root is not on sys.path.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.db import create_sac_engine  # noqa: E402

BASELINE = "0001"


def main() -> int:
    engine = create_sac_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "migrations"))
    url = os.getenv("DATABASE_URL")
    if url:
        from app.db import normalize_database_url

        cfg.set_main_option("sqlalchemy.url", normalize_database_url(url))

    if "alembic_version" not in tables and "projects" in tables:
        # Case 3: pre-Alembic schema built by create_all.
        print(f"[migrate] existing un-stamped schema detected; stamping {BASELINE}")
        command.stamp(cfg, BASELINE)
    elif not tables:
        print("[migrate] fresh database")
    else:
        print("[migrate] alembic-managed database")

    print("[migrate] upgrading to head")
    command.upgrade(cfg, "head")
    print("[migrate] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
