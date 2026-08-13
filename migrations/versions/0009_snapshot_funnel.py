"""manifest: the funnel a compile went through, on every snapshot

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-13

Adds ``context_snapshots.funnel`` — the stage-by-stage count of what happened to
everything that did NOT reach the model: considered, filtered by permission,
beaten in ranking, suppressed as a near-duplicate, faded by age, dropped for
budget. ``included`` and ``excluded`` already enumerate rows; this counts the
candidates that never became rows, which is the half that made "why didn't my
agent know that?" unanswerable from the record.

A separate column rather than more entries in ``excluded`` on purpose. That list
is the privacy manifest and is read item by item — by the console, by the API,
and by ``repeatedly_included_ids``, which pins memory based on what it finds
there. Aggregate counters mixed into it would be items that name no memory, and
every reader would have to learn to skip them.

Additive and inert on arrival: every existing snapshot keeps exactly what it
recorded and gains an empty object, which is the honest value — those compiles
did not measure a funnel, and inventing one from `included`/`excluded` would put
numbers in the audit record that nothing ever counted. NOT NULL carries a
server_default so the ALTER succeeds on a populated table, and the column is
guarded, since ``metadata.create_all`` at startup may already have created it on
a database that booted before migrating.
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if "funnel" not in _columns("context_snapshots"):
        op.add_column(
            "context_snapshots",
            # sa.JSON, matching app/db.py: Postgres gets JSON, SQLite gets TEXT,
            # and the same literal '{}' is a valid default for both.
            sa.Column("funnel", sa.JSON, nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    if "funnel" in _columns("context_snapshots"):
        op.drop_column("context_snapshots", "funnel")
