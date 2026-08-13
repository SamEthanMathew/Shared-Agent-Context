"""Billing: entitlements, seat counting, and the grace period.

Stripe itself is not exercised here — `tests/test_billing_webhook.py` covers the
event handling, and only a live test-mode run can prove the network calls. What
these tests defend is the part that decides whether a customer can use what they
paid for, which must be answerable without Stripe being reachable at all.

Three properties matter more than the rest:

* a workspace that stops paying **keeps its data** and merely cannot add more;
* a failed payment does not remove access until the grace period expires;
* seat count is derived from membership, never from anything a user can set.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.billing import FREE, PRO, plan_for
from app.billing import service
from app.db import utcnow
from app.errors import ConflictError, ForbiddenError


@pytest.fixture
def workspace(seed):
    """An organisation owned by Alice, with one context in it."""
    org = seed.store.orgs.create("Acme Inc", seed.alice_user_id)
    seed.store.orgs.attach_project(org["id"], seed.project_id)
    return org


def _go_pro(seed, org_id, *, status="active", seats=1):
    seed.store.billing.apply_subscription(
        org_id,
        subscription_id="sub_test123",
        price_id="price_monthly",
        status=status,
        quantity=seats,
        interval="month",
        current_period_end=utcnow() + timedelta(days=30),
        plan=PRO,
    )


# --- plan resolution --------------------------------------------------------


def test_a_new_workspace_is_free(seed, workspace):
    assert seed.store.billing.effective_plan(workspace["id"]).name == FREE


def test_personal_use_is_always_free(seed):
    """No organisation means no subscription to attach money to."""
    assert seed.store.billing.effective_plan(None).name == FREE


def test_an_active_subscription_grants_pro(seed, workspace):
    _go_pro(seed, workspace["id"])
    assert seed.store.billing.effective_plan(workspace["id"]).name == PRO


def test_an_unknown_plan_value_degrades_to_free(seed):
    """A bad value in the database should not take a request down."""
    assert plan_for("platinum").name == FREE
    assert plan_for(None).name == FREE


# --- the grace period -------------------------------------------------------


def test_a_failed_payment_does_not_immediately_remove_access(seed, workspace):
    """An expired card is not a decision to leave."""
    _go_pro(seed, workspace["id"], status="past_due")
    seed.store.billing.mark_payment_failed(workspace["id"])
    assert seed.store.billing.effective_plan(workspace["id"]).name == PRO
    assert seed.store.billing.in_grace_period(
        seed.store.billing.get(workspace["id"])
    ) is True


def test_access_ends_when_the_grace_period_expires(seed, workspace, monkeypatch):
    monkeypatch.setenv("SAC_BILLING_GRACE_DAYS", "14")
    _go_pro(seed, workspace["id"], status="past_due")

    from sqlalchemy import update

    from app.db import organisations

    with seed.store.engine.begin() as conn:
        conn.execute(
            update(organisations)
            .where(organisations.c.id == workspace["id"])
            .values(payment_failed_at=utcnow() - timedelta(days=15))
        )
    assert seed.store.billing.effective_plan(workspace["id"]).name == FREE


def test_repeated_failures_do_not_extend_the_grace_period(seed, workspace):
    """Stripe retries a failed invoice, and each retry is another webhook.

    Resetting the clock on every one would make the grace period unbounded.
    """
    _go_pro(seed, workspace["id"], status="past_due")
    billing = seed.store.billing
    billing.mark_payment_failed(workspace["id"])
    first = billing.get(workspace["id"])["payment_failed_at"]
    billing.mark_payment_failed(workspace["id"])
    billing.mark_payment_failed(workspace["id"])
    assert billing.get(workspace["id"])["payment_failed_at"] == first


def test_a_successful_payment_clears_the_failure(seed, workspace):
    _go_pro(seed, workspace["id"], status="past_due")
    seed.store.billing.mark_payment_failed(workspace["id"])
    _go_pro(seed, workspace["id"], status="active")
    record = seed.store.billing.get(workspace["id"])
    assert record["payment_failed_at"] is None
    assert seed.store.billing.in_grace_period(record) is False


def test_a_cancelled_subscription_has_no_entitlement(seed, workspace):
    _go_pro(seed, workspace["id"], status="canceled")
    assert seed.store.billing.effective_plan(workspace["id"]).name == FREE


# --- downgrade keeps data ---------------------------------------------------


def test_downgrading_keeps_every_context_and_memory(seed, workspace):
    """The property that makes a billing lapse survivable."""
    _go_pro(seed, workspace["id"])
    for n in range(5):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary=f"note {n}"
        )
    before = len(seed.store.memories.list_memories(seed.project_id, seed.alice_user_id))

    seed.store.billing.downgrade_to_free(workspace["id"])

    assert seed.store.billing.effective_plan(workspace["id"]).name == FREE
    after = seed.store.memories.list_memories(seed.project_id, seed.alice_user_id)
    assert len(after) == before
    # And the context itself is still there and still readable.
    assert seed.store.projects.get_project(seed.project_id) is not None


def test_downgrading_keeps_the_stripe_ids_for_history(seed, workspace):
    """Re-subscribing should be a continuation, not a fresh start."""
    _go_pro(seed, workspace["id"])
    seed.store.billing.link_customer(workspace["id"], "cus_abc")
    seed.store.billing.downgrade_to_free(workspace["id"])
    record = seed.store.billing.get(workspace["id"])
    assert record["stripe_customer_id"] == "cus_abc"
    assert record["stripe_subscription_id"] == "sub_test123"


# --- limits restrict additions, nothing else --------------------------------


def test_free_allows_exactly_one_context(seed, free_plan_limits):
    """An empty workspace may create one; a workspace with one may not create two."""
    empty = seed.store.orgs.create("Empty Co", seed.alice_user_id)
    service.check_can_add_context(seed.store, empty["id"], seed.alice_user_id)

    seed.store.orgs.attach_project(empty["id"], seed.project_id)
    with pytest.raises(ConflictError) as exc:
        service.check_can_add_context(seed.store, empty["id"], seed.alice_user_id)
    assert "Free plan allows at most 1" in str(exc.value)
    # The message has to name the way out, or it reads as a malfunction.
    assert "Upgrade to Pro" in str(exc.value)


def test_an_archived_context_does_not_count_against_the_limit(seed, workspace, free_plan_limits):
    """Archiving is how a Free workspace makes room without losing anything."""
    seed.store.projects.archive_project(seed.project_id)
    service.check_can_add_context(seed.store, workspace["id"], seed.alice_user_id)


def test_pro_lifts_the_context_limit(seed, workspace):
    _go_pro(seed, workspace["id"])
    for n in range(4):
        seed.store.orgs.attach_project(
            workspace["id"],
            seed.store.projects.create_project(
                f"Extra {n}", owner_user_id=seed.alice_user_id
            ).id,
        )
    service.check_can_add_context(seed.store, workspace["id"], seed.alice_user_id)


def test_free_allows_three_members(seed, workspace, free_plan_limits):
    orgs = seed.store.orgs
    for n in range(2):
        uid = seed.store.projects.create_user(f"m{n}@example.com", f"M{n}")
        seed.store.auth.mark_email_verified(uid)
        orgs.add_member(workspace["id"], uid)
    # alice + 2 = 3, at the limit
    with pytest.raises(ConflictError):
        service.check_can_add_member(seed.store, workspace["id"])


def test_a_context_over_the_limit_is_still_readable_after_downgrade(seed, workspace, free_plan_limits):
    """Restrict additions, never access to what already exists."""
    _go_pro(seed, workspace["id"])
    second = seed.store.projects.create_project(
        "Second", owner_user_id=seed.alice_user_id
    )
    seed.store.orgs.attach_project(workspace["id"], second.id)
    seed.store.billing.downgrade_to_free(workspace["id"])

    # Two contexts on a one-context plan: both still resolve and still read.
    for pid in (seed.project_id, second.id):
        identity = seed.store.resolve_identity(_principal(seed.alice_user_id), pid)
        assert identity.role == "owner"
        seed.store.memories.list_memories(pid, seed.alice_user_id)
    # But no third may be added.
    with pytest.raises(ConflictError):
        service.check_can_add_context(seed.store, workspace["id"], seed.alice_user_id)


def _principal(user_id: str):
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    return Principal(user_id, None, (READ_SCOPE, WRITE_SCOPE))


# --- enforcement is actually wired into the real call sites ------------------
#
# The checker functions above are easy to get right and easy to forget to call.
# These go through the paths a user actually takes.


def test_creating_a_second_personal_context_is_refused_on_free(seed, free_plan_limits):
    """Personal use is Free, so multi-context is where Pro starts."""
    from app.api import impl
    from app.identity import Principal

    principal = Principal(seed.alice_user_id, None)
    # Alice already owns one context from the seed fixture.
    with pytest.raises(ConflictError) as exc:
        impl.create_context(seed.store, principal, "A second one")
    assert "Upgrade to Pro" in str(exc.value)


def test_adding_a_fourth_member_is_refused_on_free(seed, free_plan_limits, monkeypatch):
    """Through the HTTP surface, which is where the limit has to hold."""
    from fastapi.testclient import TestClient

    from app.browser import CSRF_COOKIE, CSRF_HEADER
    from app.main import app as real_app

    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    runtime.set_store(seed.store)
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")

    client = TestClient(real_app, follow_redirects=False)
    client.post(
        "/auth/login",
        data={"email": "alice@example.com", "password": "correct-horse-battery"},
    )
    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]

    org_id = client.post("/v1/orgs", json={"name": "Capped Co"}).json()["org"]["id"]
    for n in range(2):
        uid = seed.store.projects.create_user(f"w{n}@example.com", f"W{n}")
        seed.store.auth.mark_email_verified(uid)
        r = client.post(
            f"/v1/orgs/{org_id}/members", json={"email": f"w{n}@example.com"}
        )
        assert r.status_code == 200, r.text

    # alice + 2 = 3 seats, at the Free ceiling.
    uid = seed.store.projects.create_user("over@example.com", "Over")
    seed.store.auth.mark_email_verified(uid)
    r = client.post(f"/v1/orgs/{org_id}/members", json={"email": "over@example.com"})
    assert r.status_code == 409
    assert "Upgrade to Pro" in r.json()["detail"]


# --- seats are derived, never declared --------------------------------------


def test_seat_count_comes_from_membership(seed, workspace):
    billing = seed.store.billing
    assert billing.billable_seats(workspace["id"]) == 1
    for n in range(3):
        uid = seed.store.projects.create_user(f"s{n}@example.com", f"S{n}")
        seed.store.auth.mark_email_verified(uid)
        seed.store.orgs.add_member(workspace["id"], uid)
    assert billing.billable_seats(workspace["id"]) == 4


def test_four_members_is_four_seats_at_eight_dollars(seed, workspace):
    """The spec's worked example: 4 users = quantity 4 = $32/month."""
    from app.billing.plans import PRO_MONTHLY_CENTS

    for n in range(3):
        uid = seed.store.projects.create_user(f"p{n}@example.com", f"P{n}")
        seed.store.auth.mark_email_verified(uid)
        seed.store.orgs.add_member(workspace["id"], uid)
    seats = seed.store.billing.billable_seats(workspace["id"])
    assert seats == 4
    assert seats * PRO_MONTHLY_CENTS == 3200


def test_removing_a_member_lowers_the_seat_count(seed, workspace):
    uid = seed.store.projects.create_user("leaver@example.com", "L")
    seed.store.auth.mark_email_verified(uid)
    seed.store.orgs.add_member(workspace["id"], uid)
    assert seed.store.billing.billable_seats(workspace["id"]) == 2
    seed.store.orgs.remove_member(workspace["id"], uid)
    assert seed.store.billing.billable_seats(workspace["id"]) == 1


# --- authorisation ----------------------------------------------------------


def test_only_an_org_admin_may_see_billing(seed, workspace):
    with pytest.raises(ForbiddenError):
        service.summary(seed.store, workspace["id"], seed.carol.user_id)


def test_a_plain_member_cannot_start_checkout(seed, workspace):
    uid = seed.store.projects.create_user("plain@example.com", "P")
    seed.store.auth.mark_email_verified(uid)
    seed.store.orgs.add_member(workspace["id"], uid, org_role="member")
    with pytest.raises(ForbiddenError):
        service.start_checkout(
            seed.store, workspace["id"], uid, base_url="https://sac.test"
        )


def test_checkout_is_refused_when_stripe_is_not_configured(seed, workspace, monkeypatch):
    """The product runs complete without a Stripe account; it just cannot sell."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    with pytest.raises(ConflictError) as exc:
        service.start_checkout(
            seed.store, workspace["id"], seed.alice_user_id, base_url="https://sac.test"
        )
    assert "not configured" in str(exc.value)


# --- the summary the UI renders ---------------------------------------------


def test_summary_reports_plan_usage_and_limits(seed, workspace, free_plan_limits):
    out = service.summary(seed.store, workspace["id"], seed.alice_user_id)
    assert out["plan"] == FREE
    assert out["can_manage"] is True
    assert out["seats"] == 1
    assert out["usage"]["contexts"] == 1
    assert out["limits"]["contexts"] == 1
    assert out["limits"]["members"] == 3
    assert out["prices"] == {"month_cents": 800, "year_cents": 8400}


def test_summary_shows_pro_without_limits(seed, workspace):
    _go_pro(seed, workspace["id"], seats=4)
    out = service.summary(seed.store, workspace["id"], seed.alice_user_id)
    assert out["plan"] == PRO
    assert out["limits"]["contexts"] is None
    assert out["billed_seats"] == 4
    assert out["interval"] == "month"
    assert out["current_period_end"] is not None
