"""link sharing on contexts

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

Adds the "anyone with the link" dial: ``projects.link_access`` and a
``projects.link_token`` secret.

Additive and idempotent, for the same reason 0002 is: the app calls
``metadata.create_all`` at startup, so a deployment can reach this migration
with the columns already present. Every step therefore checks first.

``link_access`` is NOT NULL, so it carries a server_default — without one the
ALTER fails on a table that already has rows. Existing contexts default to
``none``, i.e. invited people only, which is the safe reading of "this context
had no link sharing before".
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLE = "projects"


def _columns() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(TABLE)}


def _index_names() -> set[str]:
    insp = sa.inspect(op.get_bind())
    names = {i["name"] for i in insp.get_indexes(TABLE)}
    names |= {u["name"] for u in insp.get_unique_constraints(TABLE)}
    return {n for n in names if n}


def upgrade() -> None:
    columns = _columns()

    if "link_access" not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                "link_access",
                sa.String(8),
                nullable=False,
                server_default="none",
            ),
        )
    if "link_token" not in columns:
        op.add_column(TABLE, sa.Column("link_token", sa.String(64), nullable=True))

    # Uniqueness on the token is what makes a lookup by link unambiguous.
    if "uq_projects_link_token" not in _index_names():
        with op.batch_alter_table(TABLE) as batch:
            batch.create_unique_constraint("uq_projects_link_token", ["link_token"])


def downgrade() -> None:
    columns = _columns()
    if "uq_projects_link_token" in _index_names():
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint("uq_projects_link_token", type_="unique")
    if "link_token" in columns:
        op.drop_column(TABLE, "link_token")
    if "link_access" in columns:
        op.drop_column(TABLE, "link_access")
