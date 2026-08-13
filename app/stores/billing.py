"""Reading and writing a workspace's billing state.

The load-bearing function here is `effective_plan`, which answers "what is this
workspace entitled to *right now*". It is deliberately more forgiving than the
raw `plan` column, because two situations should not cost someone their service:

* a payment failed, but the grace period has not run out;
* Stripe says `past_due`, which means a retry is still pending.

In both, the customer intends to pay and usually will. Access is withdrawn only
when the grace period actually expires.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from ..billing.plans import FREE, Plan, grace_days, plan_for
from ..db import (
    agent_connections,
    billing_events,
    ensure_aware,
    memberships,
    org_members,
    organisations,
    projects,
    usage_daily,
    utcnow,
)

# Stripe statuses in which the subscription is genuinely paying its way.
HEALTHY_STATUSES = frozenset({"active", "trialing"})
# Statuses where money has not arrived but the customer has not left either.
RECOVERABLE_STATUSES = frozenset({"past_due", "unpaid", "incomplete"})


class BillingStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- reading ------------------------------------------------------------

    def get(self, org_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(organisations).where(organisations.c.id == org_id)
            ).first()
        return dict(row._mapping) if row else None

    def by_customer(self, customer_id: str) -> dict[str, Any] | None:
        """Find the workspace a Stripe customer belongs to."""
        if not customer_id:
            return None
        with self.engine.begin() as conn:
            row = conn.execute(
                select(organisations).where(
                    organisations.c.stripe_customer_id == customer_id
                )
            ).first()
        return dict(row._mapping) if row else None

    def by_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        if not subscription_id:
            return None
        with self.engine.begin() as conn:
            row = conn.execute(
                select(organisations).where(
                    organisations.c.stripe_subscription_id == subscription_id
                )
            ).first()
        return dict(row._mapping) if row else None

    def effective_plan(self, org_id: str | None) -> Plan:
        """What this workspace may actually do right now.

        Personal use — no organisation — is always Free. Going Pro means
        creating an organisation, which is also the thing that makes seats and
        shared access meaningful.
        """
        if not org_id:
            return plan_for(FREE)
        record = self.get(org_id)
        if record is None:
            return plan_for(FREE)
        return self.plan_from_record(record)

    def plan_from_record(self, record: dict[str, Any]) -> Plan:
        plan_name = record.get("plan") or FREE
        if plan_name == FREE:
            return plan_for(FREE)

        status = record.get("subscription_status")
        if status is None or status in HEALTHY_STATUSES:
            return plan_for(plan_name)

        # Money has not arrived. Keep serving until the grace period runs out —
        # a failed charge is nearly always an expired card, and taking the
        # product away the same day punishes the wrong thing.
        failed_at = ensure_aware(record.get("payment_failed_at"))
        if status in RECOVERABLE_STATUSES:
            if failed_at is None:
                return plan_for(plan_name)
            if utcnow() < failed_at + timedelta(days=grace_days()):
                return plan_for(plan_name)
            return plan_for(FREE)

        # canceled / incomplete_expired and anything unrecognised: no
        # entitlement. Data is untouched; only what they may add is limited.
        return plan_for(FREE)

    def in_grace_period(self, record: dict[str, Any]) -> bool:
        """True when payment has failed but service is still being provided."""
        if (record.get("plan") or FREE) == FREE:
            return False
        failed_at = ensure_aware(record.get("payment_failed_at"))
        if failed_at is None:
            return False
        return utcnow() < failed_at + timedelta(days=grace_days())

    # --- seat counting ------------------------------------------------------

    def billable_seats(self, org_id: str) -> int:
        """The authoritative seat count: every member of the workspace.

        Osmos computes this; Stripe is told. The reverse would let someone pay
        for three seats while using ten.
        """
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    select(func.count())
                    .select_from(org_members)
                    .where(org_members.c.org_id == org_id)
                ).scalar_one()
            )

    def usage_counts(self, org_id: str) -> dict[str, int]:
        """What the workspace is currently using, for limit checks and the UI."""
        with self.engine.begin() as conn:
            contexts = conn.execute(
                select(func.count())
                .select_from(projects)
                .where(
                    projects.c.org_id == org_id,
                    projects.c.archived_at.is_(None),
                )
            ).scalar_one()
            members = conn.execute(
                select(func.count())
                .select_from(org_members)
                .where(org_members.c.org_id == org_id)
            ).scalar_one()
            # Connected agents belonging to anyone in the workspace.
            member_ids = [
                r[0]
                for r in conn.execute(
                    select(org_members.c.user_id).where(
                        org_members.c.org_id == org_id
                    )
                ).all()
            ]
            agents = 0
            if member_ids:
                agents = conn.execute(
                    select(func.count())
                    .select_from(agent_connections)
                    .where(
                        agent_connections.c.user_id.in_(member_ids),
                        agent_connections.c.revoked_at.is_(None),
                    )
                ).scalar_one()
        return {
            "contexts": int(contexts),
            "members": int(members),
            "agents": int(agents),
        }

    def personal_usage_counts(self, user_id: str) -> dict[str, int]:
        """The same, for someone working outside any organisation."""
        with self.engine.begin() as conn:
            contexts = conn.execute(
                select(func.count())
                .select_from(projects)
                .join(memberships, memberships.c.project_id == projects.c.id)
                .where(
                    memberships.c.user_id == user_id,
                    memberships.c.role == "owner",
                    projects.c.org_id.is_(None),
                    projects.c.archived_at.is_(None),
                )
            ).scalar_one()
            agents = conn.execute(
                select(func.count())
                .select_from(agent_connections)
                .where(
                    agent_connections.c.user_id == user_id,
                    agent_connections.c.revoked_at.is_(None),
                )
            ).scalar_one()
        return {"contexts": int(contexts), "members": 1, "agents": int(agents)}

    # --- writing ------------------------------------------------------------

    def link_customer(self, org_id: str, customer_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(organisations)
                .where(organisations.c.id == org_id)
                .values(stripe_customer_id=customer_id, updated_at=utcnow())
            )

    def apply_subscription(
        self,
        org_id: str,
        *,
        subscription_id: str | None,
        price_id: str | None,
        status: str | None,
        quantity: int | None,
        interval: str | None,
        current_period_end=None,
        cancel_at_period_end: bool = False,
        plan: str | None = None,
    ) -> None:
        """Record what Stripe now says about this workspace's subscription."""
        values: dict[str, Any] = {
            "stripe_subscription_id": subscription_id,
            "stripe_price_id": price_id,
            "subscription_status": status,
            "cancel_at_period_end": 1 if cancel_at_period_end else 0,
            "updated_at": utcnow(),
        }
        if quantity is not None:
            values["billable_seats"] = int(quantity)
        if interval:
            values["billing_interval"] = interval
        if current_period_end is not None:
            values["current_period_end"] = current_period_end
        if plan is not None:
            values["plan"] = plan
        # A subscription that is paying clears any past failure.
        if status in HEALTHY_STATUSES:
            values["payment_failed_at"] = None
        with self.engine.begin() as conn:
            conn.execute(
                update(organisations)
                .where(organisations.c.id == org_id)
                .values(**values)
            )

    def mark_payment_failed(self, org_id: str) -> None:
        """Start the grace clock, but only on the first failure of a run.

        Stripe retries a failed invoice several times, and each retry is another
        webhook. Resetting the timestamp each time would extend the grace period
        indefinitely, so the first failure is the one that counts.
        """
        with self.engine.begin() as conn:
            row = conn.execute(
                select(organisations.c.payment_failed_at).where(
                    organisations.c.id == org_id
                )
            ).first()
            if row is not None and row[0] is not None:
                return
            conn.execute(
                update(organisations)
                .where(organisations.c.id == org_id)
                .values(payment_failed_at=utcnow(), updated_at=utcnow())
            )

    def clear_payment_failure(self, org_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(organisations)
                .where(organisations.c.id == org_id)
                .values(payment_failed_at=None, updated_at=utcnow())
            )

    def downgrade_to_free(self, org_id: str) -> None:
        """End the subscription's entitlement without touching a byte of data.

        The Stripe ids are kept: they are the history of what this workspace
        bought, and they make re-subscribing a continuation rather than a fresh
        start.
        """
        with self.engine.begin() as conn:
            conn.execute(
                update(organisations)
                .where(organisations.c.id == org_id)
                .values(
                    plan=FREE,
                    subscription_status="canceled",
                    cancel_at_period_end=0,
                    payment_failed_at=None,
                    billable_seats=0,
                    updated_at=utcnow(),
                )
            )

    def set_plan(self, org_id: str, plan: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(organisations)
                .where(organisations.c.id == org_id)
                .values(plan=plan, updated_at=utcnow())
            )

    # --- webhook idempotency ------------------------------------------------

    def already_processed(self, stripe_event_id: str) -> bool:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(billing_events.c.processed_at).where(
                    billing_events.c.stripe_event_id == stripe_event_id
                )
            ).first()
        return row is not None and row[0] is not None

    def begin_event(
        self, stripe_event_id: str, event_type: str, payload: dict[str, Any]
    ) -> bool:
        """Claim an event for processing. False means it is already done.

        A row whose ``processed_at`` is still NULL represents an attempt that
        failed, so it is re-claimable — otherwise a transient error during a
        handler would lose the event forever: Stripe would retry, we would see
        the existing row, and skip it.

        That does mean two simultaneous deliveries could both proceed. It is the
        better trade, because every handler is written to be safe run twice
        (`apply_subscription` overwrites, `mark_payment_failed` guards on the
        existing timestamp), whereas a permanently dropped event is not
        recoverable without hand-replaying it from the Stripe dashboard.
        """
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(
                    billing_events.c.id, billing_events.c.processed_at
                ).where(billing_events.c.stripe_event_id == stripe_event_id)
            ).first()
            if existing is not None:
                if existing[1] is not None:
                    return False  # genuinely finished
                # A previous attempt failed. Let this delivery try again.
                conn.execute(
                    update(billing_events)
                    .where(billing_events.c.id == existing[0])
                    .values(received_at=utcnow())
                )
                return True
            try:
                conn.execute(
                    billing_events.insert().values(
                        id=str(uuid.uuid4()),
                        stripe_event_id=stripe_event_id,
                        event_type=event_type,
                        payload=payload,
                        received_at=utcnow(),
                    )
                )
            except Exception:
                # Lost an insert race against a concurrent delivery.
                return False
        return True

    def finish_event(
        self, stripe_event_id: str, org_id: str | None = None, error: str | None = None
    ) -> None:
        """Mark an event finished. It will never be processed again."""
        with self.engine.begin() as conn:
            conn.execute(
                update(billing_events)
                .where(billing_events.c.stripe_event_id == stripe_event_id)
                .values(processed_at=utcnow(), org_id=org_id, error=error)
            )

    def fail_event(
        self, stripe_event_id: str, org_id: str | None, error: str
    ) -> None:
        """Record a failed attempt *without* marking it done, so a retry works."""
        with self.engine.begin() as conn:
            conn.execute(
                update(billing_events)
                .where(billing_events.c.stripe_event_id == stripe_event_id)
                .values(org_id=org_id, error=error, processed_at=None)
            )

    # --- usage / cost accounting -------------------------------------------

    def record_usage(
        self,
        *,
        org_id: str | None,
        user_id: str | None,
        **counters: int | float,
    ) -> None:
        """Add to today's usage row for a workspace (or a personal user).

        Kept entirely separate from anything Stripe bills. Seats are the price;
        this is the cost — so that any future decision about metered pricing is
        made from measurements rather than from a guess.
        """
        if not counters:
            return
        day = utcnow().strftime("%Y-%m-%d")
        with self.engine.begin() as conn:
            row = conn.execute(
                select(usage_daily.c.id).where(
                    usage_daily.c.org_id.is_(None)
                    if org_id is None
                    else usage_daily.c.org_id == org_id,
                    usage_daily.c.user_id.is_(None)
                    if user_id is None
                    else usage_daily.c.user_id == user_id,
                    usage_daily.c.day == day,
                )
            ).first()
            if row is None:
                conn.execute(
                    usage_daily.insert().values(
                        id=str(uuid.uuid4()),
                        org_id=org_id,
                        user_id=user_id,
                        day=day,
                        **{k: v for k, v in counters.items()},
                    )
                )
                return
            increments = {
                column: usage_daily.c[column] + value
                for column, value in counters.items()
                if column in usage_daily.c
            }
            if increments:
                conn.execute(
                    update(usage_daily)
                    .where(usage_daily.c.id == row[0])
                    .values(**increments)
                )

    def monthly_syncs(self, org_id: str | None, user_id: str | None) -> int:
        """Syncs so far this calendar month — the one Free usage limit."""
        prefix = utcnow().strftime("%Y-%m")
        with self.engine.begin() as conn:
            total = conn.execute(
                select(func.coalesce(func.sum(usage_daily.c.context_syncs), 0)).where(
                    usage_daily.c.org_id.is_(None)
                    if org_id is None
                    else usage_daily.c.org_id == org_id,
                    usage_daily.c.user_id.is_(None)
                    if user_id is None
                    else usage_daily.c.user_id == user_id,
                    usage_daily.c.day.startswith(prefix),
                )
            ).scalar_one()
        return int(total or 0)
