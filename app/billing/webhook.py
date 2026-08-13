"""Handling Stripe's events.

This endpoint is the only thing that grants a paid plan, which makes it the most
security-sensitive route in the product: without signature verification it would
be an unauthenticated way for anyone to hand themselves Pro. So an unset signing
secret is a hard failure, never a permissive fallback.

The second property is idempotency. Stripe retries deliveries and can send the
same event more than once, and events can arrive out of order. Every handler is
therefore safe to run twice, and `billing_events.stripe_event_id` is unique so
the second delivery is recognised rather than re-applied.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .plans import FREE, PRO, interval_for_price

HANDLED = (
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _org_from(store, obj: dict[str, Any]) -> str | None:
    """Identify the workspace an event belongs to.

    Three routes, most reliable first: metadata we set when creating the object,
    the subscription we recorded, then the customer. Any one of them is enough,
    and having three means a partially-written link still resolves.
    """
    metadata = obj.get("metadata") or {}
    org_id = metadata.get("osmos_org_id") or obj.get("client_reference_id")
    if org_id:
        return org_id

    subscription = obj.get("subscription")
    if isinstance(subscription, str):
        record = store.billing.by_subscription(subscription)
        if record:
            return record["id"]

    customer = obj.get("customer")
    if isinstance(customer, str):
        record = store.billing.by_customer(customer)
        if record:
            return record["id"]
    return None


def _subscription_fields(subscription: dict[str, Any]) -> dict[str, Any]:
    items = ((subscription.get("items") or {}).get("data")) or []
    first = items[0] if items else {}
    price = (first.get("price") or {}).get("id")
    quantity = first.get("quantity")
    interval = (
        ((first.get("price") or {}).get("recurring") or {}).get("interval")
        or interval_for_price(price or "")
    )
    return {
        "price_id": price,
        "quantity": quantity,
        "interval": interval,
        "status": subscription.get("status"),
        "current_period_end": _ts(subscription.get("current_period_end")),
        "cancel_at_period_end": bool(subscription.get("cancel_at_period_end")),
    }


# --- handlers ---------------------------------------------------------------


def _on_checkout_completed(store, obj: dict[str, Any], org_id: str) -> None:
    """The moment a workspace becomes Pro."""
    customer = obj.get("customer")
    if isinstance(customer, str):
        store.billing.link_customer(org_id, customer)

    subscription_id = obj.get("subscription")
    fields: dict[str, Any] = {}
    if isinstance(subscription_id, str):
        try:
            from . import stripe_client

            fields = _subscription_fields(
                stripe_client.get_subscription(subscription_id)
            )
        except Exception:  # noqa: BLE001
            # The subscription.updated event that follows will fill these in.
            # Granting the plan matters more than knowing the period end.
            fields = {}

    store.billing.apply_subscription(
        org_id,
        subscription_id=subscription_id if isinstance(subscription_id, str) else None,
        price_id=fields.get("price_id"),
        status=fields.get("status") or "active",
        quantity=fields.get("quantity") or store.billing.billable_seats(org_id),
        interval=fields.get("interval"),
        current_period_end=fields.get("current_period_end"),
        cancel_at_period_end=fields.get("cancel_at_period_end", False),
        plan=PRO,
    )
    store.audit.emit(
        "billing.upgraded", "organisation", org_id,
        meta={"interval": fields.get("interval")},
    )


def _on_invoice_paid(store, obj: dict[str, Any], org_id: str) -> None:
    """Money arrived: confirm entitlement and clear any failure flag."""
    store.billing.clear_payment_failure(org_id)
    record = store.billing.get(org_id) or {}
    if record.get("plan") != PRO and record.get("stripe_subscription_id"):
        store.billing.set_plan(org_id, PRO)
    store.audit.emit("billing.invoice_paid", "organisation", org_id)


def _on_payment_failed(store, obj: dict[str, Any], org_id: str) -> None:
    """Money did not arrive. Start the grace clock and tell someone.

    Service continues: an expired card is not a decision to leave, and the
    person who can fix it is often not the person hitting the product.
    """
    store.billing.mark_payment_failed(org_id)
    store.audit.emit("billing.payment_failed", "organisation", org_id)

    try:
        from .. import email as mailer
        from .plans import grace_days

        for member in store.orgs.list_members(org_id):
            if member["org_role"] == "owner" and member.get("email"):
                mailer.send_payment_failed(
                    member["email"],
                    (store.billing.get(org_id) or {}).get("name", "your workspace"),
                    grace_days(),
                )
                break
    except Exception:  # noqa: BLE001 - a failed notice must not fail the webhook
        pass


def _on_subscription_updated(store, obj: dict[str, Any], org_id: str) -> None:
    """Status, quantity, interval, or cancellation state changed."""
    fields = _subscription_fields(obj)
    # A subscription that has actually ended should not leave the plan at Pro.
    plan = FREE if fields["status"] in ("canceled", "incomplete_expired") else PRO
    store.billing.apply_subscription(
        org_id,
        subscription_id=obj.get("id"),
        price_id=fields["price_id"],
        status=fields["status"],
        quantity=fields["quantity"],
        interval=fields["interval"],
        current_period_end=fields["current_period_end"],
        cancel_at_period_end=fields["cancel_at_period_end"],
        plan=plan,
    )
    store.audit.emit(
        "billing.subscription_updated", "organisation", org_id,
        meta={"status": fields["status"], "quantity": fields["quantity"]},
    )


def _on_subscription_deleted(store, obj: dict[str, Any], org_id: str) -> None:
    """The subscription is over. Downgrade entitlement; keep every byte."""
    store.billing.downgrade_to_free(org_id)
    store.audit.emit("billing.downgraded", "organisation", org_id)


_HANDLERS = {
    "checkout.session.completed": _on_checkout_completed,
    "invoice.paid": _on_invoice_paid,
    "invoice.payment_failed": _on_payment_failed,
    "customer.subscription.updated": _on_subscription_updated,
    "customer.subscription.deleted": _on_subscription_deleted,
}


def handle(store, event: dict[str, Any]) -> dict[str, Any]:
    """Process one verified Stripe event, exactly once.

    Returns a small report rather than raising for unknown events: Stripe sends
    plenty we do not care about, and a non-2xx would make it retry them forever.
    """
    event_id = event.get("id") or ""
    event_type = event.get("type") or ""
    obj = ((event.get("data") or {}).get("object")) or {}

    if event_type not in _HANDLERS:
        return {"ok": True, "ignored": event_type}

    if store.billing.already_processed(event_id):
        return {"ok": True, "duplicate": True, "event": event_id}

    # Claim it. A concurrent redelivery loses this race and returns here.
    if not store.billing.begin_event(event_id, event_type, obj):
        return {"ok": True, "duplicate": True, "event": event_id}

    org_id = _org_from(store, obj)
    if org_id is None:
        # Nothing to apply this to, and retrying will not change that — so it is
        # finished, not failed. Recorded with a reason for diagnosis.
        store.billing.finish_event(event_id, error="no matching workspace")
        return {"ok": True, "unmatched": True, "event": event_id}

    try:
        _HANDLERS[event_type](store, obj, org_id)
    except Exception as exc:  # noqa: BLE001
        # Record the failure but leave the event *unfinished*, so Stripe's retry
        # is processed rather than dismissed as a duplicate. Re-raise so the
        # endpoint answers 5xx and that retry actually happens.
        store.billing.fail_event(event_id, org_id, str(exc)[:500])
        raise

    store.billing.finish_event(event_id, org_id=org_id)
    return {"ok": True, "handled": event_type, "org_id": org_id}
