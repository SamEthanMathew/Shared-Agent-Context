"""billing: workspace subscriptions, webhook idempotency, cost accounting

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13

Additive and inert on arrival: every existing organisation becomes ``plan='free'``
with no Stripe objects attached, which is exactly what they are today. Nobody's
access changes when this applies, and the product runs unmodified on a deployment
that has never heard of Stripe.

The unique constraint on ``billing_events.stripe_event_id`` is not decoration —
it is the idempotency mechanism. Stripe retries deliveries and can send the same
event twice, so "have we already handled this" has to be a question the database
answers, not one the application hopes about.

NOT NULL columns carry a server_default so the ALTER succeeds on populated
tables. Idempotent per object, since ``metadata.create_all`` at startup may have
created the new tables on a database that booted before migrating.
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


ORG_COLUMNS = [
    ("plan", sa.Column("plan", sa.String(16), nullable=False, server_default="free")),
    ("stripe_customer_id", sa.Column("stripe_customer_id", sa.String(64), nullable=True)),
    (
        "stripe_subscription_id",
        sa.Column("stripe_subscription_id", sa.String(64), nullable=True),
    ),
    ("stripe_price_id", sa.Column("stripe_price_id", sa.String(64), nullable=True)),
    ("billing_interval", sa.Column("billing_interval", sa.String(8), nullable=True)),
    (
        "billable_seats",
        sa.Column("billable_seats", sa.Integer, nullable=False, server_default="0"),
    ),
    (
        "subscription_status",
        sa.Column("subscription_status", sa.String(32), nullable=True),
    ),
    (
        "current_period_end",
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
    ),
    (
        "cancel_at_period_end",
        sa.Column(
            "cancel_at_period_end", sa.Integer, nullable=False, server_default="0"
        ),
    ),
    (
        "payment_failed_at",
        sa.Column("payment_failed_at", sa.DateTime(timezone=True), nullable=True),
    ),
]


def upgrade() -> None:
    existing = _columns("organisations")
    for name, column in ORG_COLUMNS:
        if name not in existing:
            op.add_column("organisations", column)

    if "organisations" in _tables():
        indexes = {
            i["name"] for i in sa.inspect(op.get_bind()).get_indexes("organisations")
        }
        if "ix_orgs_stripe_customer" not in indexes:
            op.create_index(
                "ix_orgs_stripe_customer", "organisations", ["stripe_customer_id"]
            )
        if "plan" not in existing:
            with op.batch_alter_table("organisations") as batch:
                batch.create_check_constraint(
                    "ck_org_plan", "plan IN ('free','pro','enterprise')"
                )

    tables = _tables()
    if "billing_events" not in tables:
        op.create_table(
            "billing_events",
            sa.Column("id", sa.String(36), primary_key=True),
            # The idempotency key. Two concurrent deliveries of one event race to
            # insert here and exactly one wins.
            sa.Column("stripe_event_id", sa.String(64), nullable=False, unique=True),
            sa.Column("org_id", sa.String(36), nullable=True),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("payload", sa.JSON, nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text, nullable=True),
        )
        op.create_index("ix_billing_events_org", "billing_events", ["org_id"])

    if "usage_daily" not in tables:
        op.create_table(
            "usage_daily",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), nullable=True),
            sa.Column("user_id", sa.String(36), nullable=True),
            sa.Column("day", sa.String(10), nullable=False),
            *[
                sa.Column(name, sa.Integer, nullable=False, server_default="0")
                for name in (
                    "context_syncs",
                    "context_writes",
                    "context_retrievals",
                    "embedding_tokens",
                    "llm_input_tokens",
                    "llm_output_tokens",
                    "storage_bytes",
                )
            ],
            *[
                sa.Column(name, sa.Float, nullable=False, server_default="0")
                for name in (
                    "estimated_llm_cost",
                    "estimated_storage_cost",
                    "estimated_compute_cost",
                )
            ],
            sa.UniqueConstraint("org_id", "user_id", "day", name="uq_usage_scope_day"),
        )
        op.create_index("ix_usage_day", "usage_daily", ["day"])


def downgrade() -> None:
    tables = _tables()
    if "usage_daily" in tables:
        op.drop_index("ix_usage_day", table_name="usage_daily")
        op.drop_table("usage_daily")
    if "billing_events" in tables:
        op.drop_index("ix_billing_events_org", table_name="billing_events")
        op.drop_table("billing_events")

    existing = _columns("organisations")
    if "plan" in existing:
        with op.batch_alter_table("organisations") as batch:
            batch.drop_constraint("ck_org_plan", type_="check")
    indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("organisations")}
    if "ix_orgs_stripe_customer" in indexes:
        op.drop_index("ix_orgs_stripe_customer", table_name="organisations")
    for name, _column in reversed(ORG_COLUMNS):
        if name in existing:
            op.drop_column("organisations", name)
