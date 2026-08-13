"""indexes for the hot read paths

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-12

Index-only; no data or column changes, so it is safe to apply to a live database
while the previous version is still serving.

Three additions, each for a query that already exists and currently does more
work than it needs to:

* ``ix_memories_compile_rev`` — ``compile_candidates`` filters on
  (project_id, status) and then sorts by revision to take the newest 750.
  ``ix_memories_compile`` covers the filter but not the sort, so Postgres reads
  every matching row and sorts it. Adding revision to the index lets it walk the
  index backwards and stop at 750.

* ``ix_snapshots_user`` — a person's own sync records are read by
  (project_id, user_id) ordered by time, but the only index was project-wide.
  In a busy shared context that meant scanning everyone's records to find one
  person's.

* ``ix_*_expires`` — the retention job (0006 / scripts/reaper.py) deletes by
  expiry. Without these, each pass sequentially scans the table it is pruning,
  which is exactly the table that has grown large enough to need pruning.

Guarded by an existence check, since ``metadata.create_all`` at startup may have
created them already on a database that booted before migrating.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# (index name, table, columns)
INDEXES = [
    ("ix_memories_compile_rev", "memories", ["project_id", "status", "revision"]),
    ("ix_snapshots_user", "context_snapshots", ["project_id", "user_id", "created_at"]),
    ("ix_txn_expires", "auth_transactions", ["expires_at"]),
    ("ix_codes_expires", "authorization_codes", ["expires_at"]),
    ("ix_tokens_expires", "oauth_tokens", ["expires_at"]),
    ("ix_login_sessions_expires", "login_sessions", ["expires_at"]),
    ("ix_email_tokens_expires", "email_tokens", ["expires_at"]),
]


def _existing(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return set()
    return {i["name"] for i in insp.get_indexes(table) if i.get("name")}


def upgrade() -> None:
    for name, table, columns in INDEXES:
        present = _existing(table)
        if not present and table not in set(
            sa.inspect(op.get_bind()).get_table_names()
        ):
            continue
        if name not in present:
            op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        if name in _existing(table):
            op.drop_index(name, table_name=table)
