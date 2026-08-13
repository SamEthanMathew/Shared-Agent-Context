"""Billing operations, in Osmos terms rather than Stripe's.

This is the layer the API calls. It owns three rules that the spec is explicit
about and that are easy to get wrong:

**Osmos computes seats; Stripe is told.** Never the other way round. A quantity
edited in Stripe's portal would let a workspace pay for three seats while ten
people use it, so every membership change recomputes from `org_members` and
pushes the result.

**Growing prorates, shrinking waits.** A new member has their seat immediately,
so it is charged immediately. A departing member's seat is already paid for
through the current period, so the smaller quantity takes effect at renewal —
their *access* ends at once regardless, which is the part that matters.

**Nothing here deletes anything.** Downgrade restricts what may be added; it
never touches a context or a memory.
"""
from __future__ import annotations

from typing import Any

from ..errors import ConflictError, ForbiddenError, NotFoundError
from . import stripe_client
from .plans import FREE, PRO, billing_configured, founding_coupon, price_id


def _require_billing_admin(store, org_id: str, user_id: str) -> None:
    """Only an organisation owner or admin may touch its money."""
    store.orgs.require_org_admin(org_id, user_id)


def _billing_email(store, org_id: str) -> str:
    """Who Stripe should address. The owner, falling back to any admin."""
    members = store.orgs.list_members(org_id)
    for role in ("owner", "admin"):
        for member in members:
            if member["org_role"] == role and member.get("email"):
                return member["email"]
    return ""


def ensure_customer(store, org_id: str) -> str:
    """The workspace's Stripe customer, created on first need."""
    record = store.billing.get(org_id)
    if record is None:
        raise NotFoundError("no such organisation")
    if record.get("stripe_customer_id"):
        return record["stripe_customer_id"]

    customer_id = stripe_client.create_customer(
        name=record.get("name") or "Osmos workspace",
        email=_billing_email(store, org_id),
        org_id=org_id,
    )
    store.billing.link_customer(org_id, customer_id)
    return customer_id


def start_checkout(
    store,
    org_id: str,
    user_id: str,
    *,
    interval: str = "month",
    base_url: str,
) -> dict[str, Any]:
    """Begin an upgrade. Returns the URL to send the browser to."""
    # Authorisation before configuration: someone who may not manage this
    # workspace should be refused on that basis, and learn nothing about how the
    # deployment is set up.
    _require_billing_admin(store, org_id, user_id)
    if not billing_configured():
        raise ConflictError("billing is not configured on this deployment")

    record = store.billing.get(org_id)
    if record and record.get("plan") == PRO and record.get(
        "subscription_status"
    ) in ("active", "trialing"):
        raise ConflictError("this workspace is already on Pro")

    interval = "year" if interval == "year" else "month"
    seats = max(1, store.billing.billable_seats(org_id))
    customer_id = ensure_customer(store, org_id)
    base = base_url.rstrip("/")

    session = stripe_client.create_checkout_session(
        customer_id=customer_id,
        price=price_id(interval),
        quantity=seats,
        success_url=f"{base}/app/orgs?billing=success",
        cancel_url=f"{base}/app/orgs?billing=cancelled",
        org_id=org_id,
        coupon=founding_coupon(),
    )
    store.audit.emit(
        "billing.checkout_started", "organisation", org_id,
        actor_user_id=user_id, meta={"interval": interval, "seats": seats},
    )
    return {"ok": True, "checkout_url": session["url"], "seats": seats}


def portal_url(store, org_id: str, user_id: str, *, base_url: str) -> str:
    """Stripe's own screen for cards, invoices, and cancellation."""
    if not billing_configured():
        raise ConflictError("billing is not configured on this deployment")
    _require_billing_admin(store, org_id, user_id)
    record = store.billing.get(org_id)
    if not record or not record.get("stripe_customer_id"):
        raise ConflictError("this workspace has no billing account yet")
    return stripe_client.create_portal_session(
        customer_id=record["stripe_customer_id"],
        return_url=f"{base_url.rstrip('/')}/app/orgs",
    )


def sync_seats(store, org_id: str, *, growing: bool) -> int | None:
    """Push the authoritative seat count to Stripe.

    Called after any membership change. Returns the new quantity, or None when
    there is nothing to bill — a Free workspace, or a deployment with no Stripe.

    Deliberately forgiving: a failure here must not undo the membership change
    the user actually asked for. The next change, or the next webhook, corrects
    the quantity.
    """
    record = store.billing.get(org_id)
    if not record or record.get("plan") == FREE:
        return None
    subscription_id = record.get("stripe_subscription_id")
    if not subscription_id or not billing_configured():
        return None

    seats = max(1, store.billing.billable_seats(org_id))
    if seats == record.get("billable_seats"):
        return seats

    try:
        stripe_client.update_quantity(subscription_id, seats, prorate=growing)
    except Exception as exc:  # noqa: BLE001 - never block a membership change
        store.audit.emit(
            "billing.seat_sync_failed", "organisation", org_id,
            meta={"seats": seats, "error": str(exc)[:200]},
        )
        return None

    store.billing.apply_subscription(
        org_id,
        subscription_id=subscription_id,
        price_id=record.get("stripe_price_id"),
        status=record.get("subscription_status"),
        quantity=seats,
        interval=record.get("billing_interval"),
    )
    store.audit.emit(
        "billing.seats_changed", "organisation", org_id,
        meta={"seats": seats, "prorated": growing},
    )
    return seats


def cancel(store, org_id: str, user_id: str) -> dict[str, Any]:
    """Stop renewing. Pro continues until the period they paid for ends."""
    _require_billing_admin(store, org_id, user_id)
    record = store.billing.get(org_id)
    if not record or not record.get("stripe_subscription_id"):
        raise ConflictError("this workspace has no subscription to cancel")
    stripe_client.cancel_at_period_end(record["stripe_subscription_id"])
    store.billing.apply_subscription(
        org_id,
        subscription_id=record["stripe_subscription_id"],
        price_id=record.get("stripe_price_id"),
        status=record.get("subscription_status"),
        quantity=record.get("billable_seats"),
        interval=record.get("billing_interval"),
        cancel_at_period_end=True,
    )
    store.audit.emit(
        "billing.cancel_scheduled", "organisation", org_id, actor_user_id=user_id,
    )
    return {"ok": True, "cancel_at_period_end": True}


# --- entitlement checks used by the rest of the app -------------------------
#
# Each of these is called at the moment something is *added*. None of them ever
# removes or hides what already exists: a workspace that drops to Free keeps
# every context and every memory, and simply cannot create more until it is
# under the limit again. Billing lapses are usually an expired card.


def check_can_add_context(store, org_id: str | None, user_id: str) -> None:
    plan = store.billing.effective_plan(org_id)
    if plan.max_contexts is None:
        return
    counts = (
        store.billing.usage_counts(org_id)
        if org_id
        else store.billing.personal_usage_counts(user_id)
    )
    from .plans import enforce

    enforce(plan, "max_contexts", counts["contexts"], "contexts")


def check_can_add_member(store, org_id: str) -> None:
    plan = store.billing.effective_plan(org_id)
    if plan.max_members is None:
        return
    from .plans import enforce

    enforce(
        plan, "max_members", store.billing.usage_counts(org_id)["members"], "members"
    )


def check_can_connect_agent(store, org_id: str | None, user_id: str) -> None:
    plan = store.billing.effective_plan(org_id)
    if plan.max_agents is None:
        return
    counts = (
        store.billing.usage_counts(org_id)
        if org_id
        else store.billing.personal_usage_counts(user_id)
    )
    from .plans import enforce

    enforce(plan, "max_agents", counts["agents"], "connected agents")


def summary(store, org_id: str, user_id: str) -> dict[str, Any]:
    """Everything the billing screen needs, in one call."""
    role = store.orgs.get_org_role(org_id, user_id)
    if role is None:
        raise ForbiddenError("no such organisation")

    record = store.billing.get(org_id) or {}
    plan = store.billing.plan_from_record(record)
    usage = store.billing.usage_counts(org_id)
    seats = store.billing.billable_seats(org_id)
    period_end = record.get("current_period_end")

    return {
        "ok": True,
        "plan": plan.name,
        "plan_label": plan.label,
        "your_role": role,
        "can_manage": role in ("owner", "admin"),
        "billing_configured": billing_configured(),
        "test_mode": stripe_client.is_test_mode(),
        "seats": seats,
        "billed_seats": record.get("billable_seats") or 0,
        "interval": record.get("billing_interval"),
        "status": record.get("subscription_status"),
        "cancel_at_period_end": bool(record.get("cancel_at_period_end")),
        "current_period_end": period_end.isoformat() if period_end else None,
        "in_grace_period": store.billing.in_grace_period(record),
        "has_billing_account": bool(record.get("stripe_customer_id")),
        "usage": usage,
        "limits": {
            "contexts": plan.max_contexts,
            "members": plan.max_members,
            "agents": plan.max_agents,
            "syncs_per_month": plan.max_syncs_per_month,
        },
        "monthly_syncs": store.billing.monthly_syncs(org_id, None),
        "prices": {"month_cents": 800, "year_cents": 8400},
    }
