"""The shape of the objects Stripe actually sends.

Every other billing test builds its own event payloads, which proves our logic is
self-consistent but cannot catch the failure this file is about: Stripe *moving a
field*. The billing code was written against an older API version and then only
ever exercised against stubs that copied its assumptions, so two removals went
unnoticed until it was run against a real account on 2025-10-29.clover.

Both are the same class of bug and both are silent — no exception, no error, just
a field that is `None` forever. So each test here pins the modern location, and
its sibling pins the legacy one, because an account pinned to an older API
version must keep working too.

The payloads below are trimmed copies of genuine test-mode objects.
"""
from __future__ import annotations

import time

import pytest

from app.billing import PRO
from app.billing import webhook
from app.db import ensure_aware


@pytest.fixture
def workspace(seed):
    org = seed.store.orgs.create("Shapes Inc", seed.alice_user_id)
    seed.store.orgs.attach_project(org["id"], seed.project_id)
    seed.store.billing.link_customer(org["id"], "cus_shapes")
    return org


def _event(event_type: str, obj: dict, event_id: str = "evt_shape") -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


# --- current_period_end moved onto the subscription item --------------------
#
# Stripe removed `current_period_start` / `current_period_end` from the
# Subscription object in API version 2025-03-31.basil and put them on each
# subscription item instead. Reading only the old location yields None against
# every current account, which quietly emptied the renewal date out of the
# billing screen and left "Pro until <date>" with no date to show.


def _modern_subscription(org_id: str, period_end: int) -> dict:
    """A subscription as 2025-03-31.basil and later send it."""
    return {
        "id": "sub_modern",
        "status": "active",
        "customer": "cus_shapes",
        "cancel_at_period_end": False,
        "metadata": {"osmos_org_id": org_id},
        "items": {
            "data": [
                {
                    "id": "si_modern",
                    "quantity": 3,
                    # The period lives here now, not on the subscription.
                    "current_period_start": period_end - 30 * 86400,
                    "current_period_end": period_end,
                    "price": {"id": "price_m", "recurring": {"interval": "month"}},
                }
            ]
        },
    }


def test_the_renewal_date_is_read_from_the_subscription_item(seed, workspace):
    """Stripe moved the billing period onto the item; we must follow it there.

    Reading only `subscription.current_period_end` returns None on every API
    version from 2025-03-31.basil onwards, so `organisations.current_period_end`
    was never written — the renewal date vanished from the billing screen and a
    scheduled cancellation could not say when access actually ends.
    """
    period_end = int(time.time()) + 30 * 86400
    webhook.handle(
        seed.store,
        _event(
            "customer.subscription.updated",
            _modern_subscription(workspace["id"], period_end),
        ),
    )
    recorded = seed.store.billing.get(workspace["id"])["current_period_end"]
    assert recorded is not None
    assert int(ensure_aware(recorded).timestamp()) == period_end


def test_the_legacy_top_level_renewal_date_still_works(seed, workspace):
    """An account pinned to a pre-basil version must keep working unchanged."""
    period_end = int(time.time()) + 30 * 86400
    legacy = _modern_subscription(workspace["id"], period_end)
    legacy["current_period_end"] = period_end
    del legacy["items"]["data"][0]["current_period_end"]

    webhook.handle(seed.store, _event("customer.subscription.updated", legacy))
    recorded = seed.store.billing.get(workspace["id"])["current_period_end"]
    assert int(ensure_aware(recorded).timestamp()) == period_end


# --- invoice.subscription moved under invoice.parent ------------------------
#
# The same release removed `subscription` from the Invoice object. It now lives
# at `invoice.parent.subscription_details.subscription`, with the subscription's
# metadata alongside it — which is where our `osmos_org_id` marker ends up.


def _modern_invoice(org_id: str | None = None, subscription: str = "sub_modern") -> dict:
    """An invoice as 2025-03-31.basil and later send it."""
    return {
        "id": "in_modern",
        "status": "paid",
        # Deliberately absent: no top-level `subscription`, and invoice metadata
        # is empty because we set ours on the subscription, not the invoice.
        "metadata": {},
        "parent": {
            "type": "subscription_details",
            "subscription_details": {
                "subscription": subscription,
                "metadata": {"osmos_org_id": org_id} if org_id else {},
            },
        },
    }


def test_an_invoice_is_matched_by_the_metadata_under_parent(seed):
    """The marker we set on the subscription is the only reliable route left.

    `_org_from` claims three ways to identify a workspace, most reliable first.
    On a current API version the first two were both dead for invoices — invoice
    metadata is empty and `invoice.subscription` no longer exists — leaving only
    the customer lookup. An invoice for a workspace whose customer link had not
    been written yet was therefore dropped as unmatched, losing a payment
    failure or a paid confirmation with no way to replay it but by hand.
    """
    org = seed.store.orgs.create("Unlinked Co", seed.alice_user_id)
    # No link_customer, and the invoice names no customer we know.
    out = webhook.handle(
        seed.store,
        _event("invoice.paid", _modern_invoice(org_id=org["id"])),
    )
    assert out.get("handled") == "invoice.paid"
    assert out["org_id"] == org["id"]


def test_an_invoice_is_matched_by_the_subscription_under_parent(seed, workspace):
    """The second route: the subscription id we already recorded."""
    seed.store.billing.apply_subscription(
        workspace["id"], subscription_id="sub_recorded", price_id="price_m",
        status="active", quantity=2, interval="month", plan=PRO,
    )
    invoice = _modern_invoice(subscription="sub_recorded")
    invoice["customer"] = "cus_someone_else"

    out = webhook.handle(seed.store, _event("invoice.paid", invoice))
    assert out.get("handled") == "invoice.paid"
    assert out["org_id"] == workspace["id"]


def test_the_legacy_top_level_invoice_subscription_still_works(seed, workspace):
    """Pre-basil invoices carry `subscription` at the top level."""
    seed.store.billing.apply_subscription(
        workspace["id"], subscription_id="sub_legacy", price_id="price_m",
        status="active", quantity=1, interval="month", plan=PRO,
    )
    out = webhook.handle(
        seed.store,
        _event(
            "invoice.paid",
            {"id": "in_legacy", "customer": "cus_other", "subscription": "sub_legacy"},
        ),
    )
    assert out["org_id"] == workspace["id"]
