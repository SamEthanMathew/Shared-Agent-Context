"""federated sign-in identities

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12

One new table linking a Google or GitHub account to a local user. Nothing
existing changes, so there is no data migration.

Guarded by an existence check for the same reason 0002 and 0003 are: the app
runs ``metadata.create_all`` at startup, and create_all *does* create missing
tables — so a boot that happens before this migration will already have made
it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLE = "sso_identities"


def upgrade() -> None:
    if TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_account_id", sa.String(128), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "provider", "provider_account_id", name="uq_sso_provider_account"
        ),
    )
    op.create_index("ix_sso_user", TABLE, ["user_id"])


def downgrade() -> None:
    if TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index("ix_sso_user", table_name=TABLE)
    op.drop_table(TABLE)
