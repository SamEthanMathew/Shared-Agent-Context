"""organisations above contexts

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12

Additive, and deliberately inert on arrival: every existing context keeps
``org_id = NULL`` and ``org_access = 'none'``, and every existing membership
becomes ``source = 'direct'``. Nobody's access changes when this applies.

That last default is the important one. ``source`` distinguishes an explicit
invitation from access derived from an organisation, and removing someone from an
organisation deletes only their ``'org'`` rows. Backfilling existing rows as
``'direct'`` is therefore the safe reading: access that predates organisations
was granted by a human, and must survive.

NOT NULL columns carry a server_default so the ALTER succeeds on populated
tables. Idempotent per object, since ``metadata.create_all`` at startup may have
created the new tables on a database that booted before migrating.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "organisations" not in tables:
        op.create_table(
            "organisations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(120), nullable=True, unique=True),
            sa.Column(
                "created_by_user_id",
                sa.String(36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "org_members" not in tables:
        op.create_table(
            "org_members",
            sa.Column(
                "org_id",
                sa.String(36),
                sa.ForeignKey("organisations.id"),
                primary_key=True,
            ),
            sa.Column(
                "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
            ),
            sa.Column(
                "org_role", sa.String(16), nullable=False, server_default="member"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "org_role IN ('owner','admin','member')", name="ck_org_role"
            ),
        )
        op.create_index("ix_org_members_user", "org_members", ["user_id"])

    project_columns = _columns("projects")
    if "org_id" not in project_columns:
        op.add_column("projects", sa.Column("org_id", sa.String(36), nullable=True))
        op.create_index("ix_projects_org", "projects", ["org_id"])
    if "org_access" not in project_columns:
        op.add_column(
            "projects",
            sa.Column(
                "org_access", sa.String(8), nullable=False, server_default="none"
            ),
        )
        with op.batch_alter_table("projects") as batch:
            batch.create_check_constraint(
                "ck_project_org_access", "org_access IN ('none','view','edit')"
            )

    if "source" not in _columns("memberships"):
        # 'direct' for everything that already exists: access granted before
        # organisations existed came from a human, and must not be revocable by
        # an organisation change.
        op.add_column(
            "memberships",
            sa.Column("source", sa.String(8), nullable=False, server_default="direct"),
        )
        with op.batch_alter_table("memberships") as batch:
            batch.create_check_constraint(
                "ck_membership_source", "source IN ('direct','org')"
            )


def downgrade() -> None:
    if "source" in _columns("memberships"):
        with op.batch_alter_table("memberships") as batch:
            batch.drop_constraint("ck_membership_source", type_="check")
        op.drop_column("memberships", "source")

    project_columns = _columns("projects")
    if "org_access" in project_columns:
        with op.batch_alter_table("projects") as batch:
            batch.drop_constraint("ck_project_org_access", type_="check")
        op.drop_column("projects", "org_access")
    if "org_id" in project_columns:
        op.drop_index("ix_projects_org", table_name="projects")
        op.drop_column("projects", "org_id")

    tables = _tables()
    if "org_members" in tables:
        op.drop_index("ix_org_members_user", table_name="org_members")
        op.drop_table("org_members")
    if "organisations" in tables:
        op.drop_table("organisations")
