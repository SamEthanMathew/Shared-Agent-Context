"""Stripe webhook handling.

This endpoint is the only thing in the product that grants a paid plan, which
makes it the most security-sensitive route here: without signature verification
it is an unauthenticated way for anyone to hand themselves Pro.

The other half is delivery semantics, which are genuinely awkward and easy to
get subtly wrong. Stripe retries, duplicates, and reorders. So every handler has
to be safe run twice, a duplicate must be recognised rather than re-applied, and
— the case that bit me while writing this — a *failed* attempt must stay
retryable rather than being recorded as done.
"""
from __future__ import annotations

import time

import pytest

from app.billing import FREE, PRO
from app.billing import webhook
from app.db import utcnow


@pytest.fixture
def workspace(seed):
    org = seed.store.orgs.create("Acme Inc", seed.alice_user_id)
    seed.store.orgs.attach_project(org["id"], seed.project_id)
    seed.store.billing.link_customer(org["id"], "cus_acme")
    return org


def _event(event_type: str, obj: dict, event_id: str = "evt_1") -> dict:
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def _subscription(org_id: str, *, status="active", quantity=1, sub_id="sub_1") -> dict:
    return {
        "id": sub_id,
        "status": status,
        "customer": "cus_acme",
        "cancel_at_period_end": False,
        "current_period_end": int(time.time()) + 30 * 86400,
        "metadata": {"osmos_org_id": org_id},
        "items": {
            "data": [
                {
                    "id": "si_1",
                    "quantity": quantity,
                    "price": {"id": "price_m", "recurring": {"interval": "month"}},
                }
            ]
        },
    }


# --- upgrade ----------------------------------------------------------------


def test_checkout_completed_makes_the_workspace_pro(seed, workspace):
    out = webhook.handle(
        seed.store,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "customer": "cus_acme",
                "subscription": "sub_1",
                "client_reference_id": workspace["id"],
                "metadata": {"osmos_org_id": workspace["id"]},
            },
        ),
    )
    assert out["handled"] == "checkout.session.completed"
    assert seed.store.billing.effective_plan(workspace["id"]).name == PRO


def test_the_workspace_is_found_by_metadata_even_without_a_link(seed):
    """Metadata is the most reliable route, and works before linking exists."""
    org = seed.store.orgs.create("Fresh Co", seed.alice_user_id)
    webhook.handle(
        seed.store,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_2",
                "customer": "cus_fresh",
                "subscription": "sub_2",
                "metadata": {"osmos_org_id": org["id"]},
            },
        ),
    )
    record = seed.store.billing.get(org["id"])
    assert record["plan"] == PRO
    assert record["stripe_customer_id"] == "cus_fresh"


def test_an_event_for_an_unknown_workspace_is_accepted_not_retried(seed):
    """Retrying will never make it match, so it is finished, not failed."""
    out = webhook.handle(
        seed.store,
        _event("invoice.paid", {"id": "in_x", "customer": "cus_nobody"}),
    )
    assert out["ok"] is True and out["unmatched"] is True


# --- idempotency ------------------------------------------------------------


def test_a_duplicate_delivery_is_not_applied_twice(seed, workspace):
    event = _event(
        "customer.subscription.updated", _subscription(workspace["id"], quantity=5)
    )
    first = webhook.handle(seed.store, event)
    second = webhook.handle(seed.store, event)
    assert first.get("handled")
    assert second.get("duplicate") is True
    assert seed.store.billing.get(workspace["id"])["billable_seats"] == 5


def test_a_failed_handler_leaves_the_event_retryable(seed, workspace, monkeypatch):
    """The bug this test exists for.

    Marking an event processed in the failure path meant Stripe's retry was
    dismissed as a duplicate — a transient error would lose the event for good,
    recoverable only by hand-replaying it from the dashboard.
    """
    event = _event("invoice.paid", {"id": "in_1", "customer": "cus_acme"})

    def _boom(*args, **kwargs):
        raise RuntimeError("database blipped")

    monkeypatch.setattr(seed.store.billing, "clear_payment_failure", _boom)
    with pytest.raises(RuntimeError):
        webhook.handle(seed.store, event)

    # Not recorded as done, so the retry is processed rather than skipped.
    assert seed.store.billing.already_processed("evt_1") is False

    monkeypatch.undo()
    retried = webhook.handle(seed.store, event)
    assert retried.get("handled") == "invoice.paid"
    assert seed.store.billing.already_processed("evt_1") is True


def test_unhandled_event_types_are_acknowledged(seed):
    """A non-2xx would make Stripe retry events we will never care about."""
    out = webhook.handle(
        seed.store, _event("customer.created", {"id": "cus_zz"})
    )
    assert out["ok"] is True and out["ignored"] == "customer.created"


# --- payment failure and the grace period -----------------------------------


def test_payment_failed_starts_the_grace_period_without_removing_access(
    seed, workspace
):
    webhook.handle(
        seed.store,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1",
                "customer": "cus_acme",
                "subscription": "sub_1",
                "metadata": {"osmos_org_id": workspace["id"]},
            },
        ),
    )
    webhook.handle(
        seed.store,
        _event(
            "invoice.payment_failed",
            {"id": "in_2", "customer": "cus_acme", "subscription": "sub_1"},
            event_id="evt_fail",
        ),
    )
    record = seed.store.billing.get(workspace["id"])
    assert record["payment_failed_at"] is not None
    # Still serving.
    assert seed.store.billing.effective_plan(workspace["id"]).name == PRO
    assert seed.store.billing.in_grace_period(record) is True


def test_a_later_paid_invoice_clears_the_failure(seed, workspace):
    seed.store.billing.apply_subscription(
        workspace["id"], subscription_id="sub_1", price_id="price_m",
        status="past_due", quantity=1, interval="month", plan=PRO,
    )
    seed.store.billing.mark_payment_failed(workspace["id"])
    webhook.handle(
        seed.store,
        _event(
            "invoice.paid",
            {"id": "in_3", "customer": "cus_acme", "subscription": "sub_1"},
            event_id="evt_paid",
        ),
    )
    assert seed.store.billing.get(workspace["id"])["payment_failed_at"] is None


# --- subscription lifecycle -------------------------------------------------


def test_subscription_updated_records_status_and_quantity(seed, workspace):
    webhook.handle(
        seed.store,
        _event(
            "customer.subscription.updated",
            _subscription(workspace["id"], status="active", quantity=7),
        ),
    )
    record = seed.store.billing.get(workspace["id"])
    assert record["subscription_status"] == "active"
    assert record["billable_seats"] == 7
    assert record["billing_interval"] == "month"
    assert record["current_period_end"] is not None


def test_a_scheduled_cancellation_is_recorded_but_still_serves(seed, workspace):
    obj = _subscription(workspace["id"])
    obj["cancel_at_period_end"] = True
    webhook.handle(seed.store, _event("customer.subscription.updated", obj))
    record = seed.store.billing.get(workspace["id"])
    assert record["cancel_at_period_end"] == 1
    # Paid for, so still Pro until the period actually ends.
    assert seed.store.billing.effective_plan(workspace["id"]).name == PRO


def test_subscription_deleted_downgrades_without_deleting_data(seed, workspace):
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Survives cancellation."
    )
    webhook.handle(
        seed.store,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1", "customer": "cus_acme", "subscription": "sub_1",
                "metadata": {"osmos_org_id": workspace["id"]},
            },
        ),
    )
    webhook.handle(
        seed.store,
        _event(
            "customer.subscription.deleted",
            _subscription(workspace["id"], status="canceled"),
            event_id="evt_del",
        ),
    )
    assert seed.store.billing.effective_plan(workspace["id"]).name == FREE
    memories = seed.store.memories.list_memories(seed.project_id, seed.alice_user_id)
    assert any(m.summary == "Survives cancellation." for m in memories)


def test_a_terminal_status_in_an_update_also_downgrades(seed, workspace):
    """An update can carry the end state without a separate deleted event."""
    webhook.handle(
        seed.store,
        _event(
            "customer.subscription.updated",
            _subscription(workspace["id"], status="canceled"),
        ),
    )
    assert seed.store.billing.get(workspace["id"])["plan"] == FREE


def test_a_late_invoice_paid_does_not_resurrect_a_cancelled_workspace(
    seed, workspace
):
    """The bug this test exists for, found running against a real account.

    Stripe does not order deliveries, and the final invoice of a cancelled
    subscription is paid at almost the same moment the subscription ends — so
    `invoice.paid` routinely lands *after* `customer.subscription.deleted`.

    `_on_invoice_paid` re-granted Pro to any workspace that was not currently Pro
    but still had a subscription id, and `downgrade_to_free` deliberately keeps
    those ids as purchase history. So the straggler flipped `plan` back to `pro`
    on a workspace that had genuinely left. Entitlement happened to survive it
    because `plan_from_record` also weighs the cancelled status, but the row was
    then self-contradictory, and `sync_seats` — which skips only Free workspaces
    — would go on pushing seat counts at a dead subscription on every membership
    change, failing every time.
    """
    webhook.handle(
        seed.store,
        _event(
            "checkout.session.completed",
            {
                "id": "cs_1", "customer": "cus_acme", "subscription": "sub_1",
                "metadata": {"osmos_org_id": workspace["id"]},
            },
        ),
    )
    webhook.handle(
        seed.store,
        _event(
            "customer.subscription.deleted",
            _subscription(workspace["id"], status="canceled"),
            event_id="evt_gone",
        ),
    )
    assert seed.store.billing.get(workspace["id"])["plan"] == FREE

    webhook.handle(
        seed.store,
        _event(
            "invoice.paid",
            {"id": "in_final", "customer": "cus_acme", "subscription": "sub_1"},
            event_id="evt_late_paid",
        ),
    )
    record = seed.store.billing.get(workspace["id"])
    assert record["plan"] == FREE
    assert seed.store.billing.effective_plan(workspace["id"]).name == FREE


def test_an_invoice_paid_still_rescues_a_workspace_whose_checkout_was_lost(
    seed, workspace
):
    """The case the resurrection guard must not break.

    If `checkout.session.completed` never arrives, `invoice.paid` is the only
    signal that a workspace has paid, and it must still grant Pro. The guard is
    on the subscription being *finished*, not on it being unknown.
    """
    seed.store.billing.apply_subscription(
        workspace["id"], subscription_id="sub_1", price_id="price_m",
        status=None, quantity=1, interval="month",
    )
    webhook.handle(
        seed.store,
        _event(
            "invoice.paid",
            {"id": "in_first", "customer": "cus_acme", "subscription": "sub_1"},
            event_id="evt_rescue",
        ),
    )
    assert seed.store.billing.get(workspace["id"])["plan"] == PRO


# --- the HTTP endpoint ------------------------------------------------------


@pytest.fixture
def api(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    return TestClient(app, follow_redirects=False), wired


def test_an_unsigned_webhook_is_rejected(api, monkeypatch):
    """Without this the endpoint hands out paid plans to anyone who asks."""
    c, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    r = c.post(
        "/api/webhooks/stripe",
        json=_event("checkout.session.completed", {"id": "cs_evil"}),
    )
    assert r.status_code == 400


def test_a_missing_signing_secret_refuses_rather_than_trusting(api, monkeypatch):
    """Fail closed: an unset secret must never mean "accept everything"."""
    c, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    r = c.post(
        "/api/webhooks/stripe",
        json=_event("checkout.session.completed", {"id": "cs_evil"}),
        headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert r.status_code == 400


def test_a_correctly_signed_webhook_is_processed(api, monkeypatch):
    """Signed with the real Stripe scheme, so this exercises verification."""
    import hashlib
    import hmac
    import json

    c, seed = api
    secret = "whsec_testsecret"
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)

    org = seed.store.orgs.create("Signed Co", seed.alice_user_id)
    body = json.dumps(
        _event(
            "checkout.session.completed",
            {
                "id": "cs_signed", "customer": "cus_signed",
                "subscription": "sub_signed",
                "metadata": {"osmos_org_id": org["id"]},
            },
            event_id="evt_signed",
        )
    ).encode()

    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()

    r = c.post(
        "/api/webhooks/stripe",
        content=body,
        headers={
            "stripe-signature": f"t={timestamp},v1={signature}",
            "content-type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    assert seed.store.billing.get(org["id"])["plan"] == PRO


def test_the_webhook_is_not_behind_csrf_or_auth(api, monkeypatch):
    """It carries no session and no bearer token — only a signature.

    A 400 (bad signature) rather than a 401/403 proves it reached the handler.
    """
    c, _ = api
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    r = c.post("/api/webhooks/stripe", content=b"{}")
    assert r.status_code == 400
    assert r.json()["detail"] != "csrf_required"
