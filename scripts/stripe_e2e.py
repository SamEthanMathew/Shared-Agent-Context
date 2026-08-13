"""Drive the whole billing lifecycle against a real Stripe test-mode account.

    source your test env, then:
    PYTHONPATH=. python scripts/stripe_e2e.py

What this is for: every other billing test in the suite runs against a stub, so
it proves our logic is self-consistent but says nothing about whether the objects
Stripe actually sends look like the ones we assumed. This script closes that gap.
It creates throwaway organisations in a scratch database, performs real Stripe
operations, and feeds the **real events Stripe emits** through the real HTTP
webhook route with a real signature — then checks both sides of every case: what
Stripe believes, and what the `organisations` row says.

Two places where fidelity is deliberately imperfect, because the API cannot do
better:

* A Checkout Session cannot be completed without a browser, so
  `checkout.session.completed` is synthesised — but from a *real* session created
  by our own `service.start_checkout` and a *real* subscription id, so only the
  event envelope is manufactured.
* Renewals, dunning, and end-of-period cancellation need time to pass, so those
  run on Stripe test clocks.

Everything else — signature verification, event shapes, proration, seat pushes,
duplicate delivery — is the genuine article.

Safe to re-run. It only ever touches objects it created, and deletes them at the
end unless `--keep` is passed.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

WEBHOOK_PATH = "/api/webhooks/stripe"

# Stripe's test payment-method tokens. Raw card numbers are rejected by the API
# unless an account has raw-card-data access, so the tokens are the supported way
# to name a specific test card: pm_card_chargeCustomerFail is 4000000000000341,
# the card that attaches to a customer successfully and then fails every charge.
GOOD_CARD = "pm_card_visa"
FAILING_CARD = "pm_card_chargeCustomerFail"
UPDATED_CARD = "pm_card_mastercard"


# --- result recording -------------------------------------------------------


class Report:
    """Every assertion, so one failure does not hide the rest."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []
        self.section = "setup"

    def begin(self, section: str) -> None:
        self.section = section
        print(f"\n=== {section} " + "=" * max(0, 62 - len(section)))

    def check(self, label: str, actual: Any, expected: Any) -> bool:
        ok = actual == expected
        self.rows.append((self.section, label, ok, f"{actual!r} (want {expected!r})"))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {actual!r}"
              + ("" if ok else f"  EXPECTED {expected!r}"))
        return ok

    def note(self, label: str, value: Any) -> None:
        print(f"  [info] {label}: {value!r}")

    def truthy(self, label: str, actual: Any) -> bool:
        ok = bool(actual)
        self.rows.append((self.section, label, ok, repr(actual)))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {actual!r}")
        return ok

    def summary(self) -> int:
        failed = [r for r in self.rows if not r[2]]
        print("\n" + "=" * 70)
        print(f"{len(self.rows) - len(failed)}/{len(self.rows)} checks passed")
        for section, label, _, detail in failed:
            print(f"  FAIL  {section} :: {label} -> {detail}")
        return 1 if failed else 0


# --- Stripe object helpers --------------------------------------------------


def plain(value: Any) -> Any:
    """A StripeObject graph as ordinary dicts, for JSON serialisation.

    StripeObject subclasses dict, so a plain recursive copy is enough — and it
    avoids `to_dict_recursive`, which the SDK now warns is internal-only.
    """
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def item_of(subscription: dict[str, Any]) -> dict[str, Any]:
    return subscription["items"]["data"][0]


def period_end_of(subscription: dict[str, Any]) -> int | None:
    """Where the current period actually lives on a modern API version.

    Stripe moved `current_period_end` off the subscription and onto each
    subscription item in 2025-03-31.basil. Reading only the old location returns
    None forever against any current account.
    """
    return item_of(subscription).get("current_period_end") or subscription.get(
        "current_period_end"
    )


# --- the harness ------------------------------------------------------------


class Harness:
    def __init__(self, db_path: str) -> None:
        import logging

        import stripe as stripe_sdk

        from app import runtime
        from app.stores import SACStore

        # The SDK narrates every HTTP call at INFO, which buries the assertions.
        logging.getLogger("stripe").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)

        self.stripe = stripe_sdk
        self.stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        self.secret = os.environ["STRIPE_WEBHOOK_SECRET"]

        Path(db_path).unlink(missing_ok=True)
        self.store = SACStore(f"sqlite:///{db_path}")
        self.store.init()
        runtime.set_store(self.store)

        from fastapi.testclient import TestClient

        from app.main import app

        self.client = TestClient(app)
        self.report = Report()

        self.our_customers: set[str] = set()
        self.clocks: list[str] = []
        self.delivered: set[str] = set()
        self.cursor = int(time.time()) - 60

    # --- webhook delivery ---------------------------------------------------

    def deliver(self, event: dict[str, Any], *, secret: str | None = None):
        """POST an event to the real route, signed the way Stripe signs."""
        body = json.dumps(event).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            (secret or self.secret).encode(),
            f"{timestamp}.".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        return self.client.post(
            WEBHOOK_PATH,
            content=body,
            headers={
                "stripe-signature": f"t={timestamp},v1={signature}",
                "content-type": "application/json",
            },
        )

    def _drain(self) -> list[dict[str, Any]]:
        """Deliver every not-yet-seen real event belonging to our customers.

        Oldest first, because ordering is part of what is being tested.
        """
        from app.billing.webhook import HANDLED

        fetched = [
            plain(e)
            for e in self.stripe.Event.list(
                created={"gte": self.cursor}, limit=100
            ).auto_paging_iter()
        ]
        applied = []
        for event in reversed(fetched):
            if event["id"] in self.delivered or event["type"] not in HANDLED:
                continue
            obj = (event.get("data") or {}).get("object") or {}
            if obj.get("customer") not in self.our_customers:
                continue
            response = self.deliver(event)
            self.delivered.add(event["id"])
            applied.append({"event": event, "status": response.status_code,
                            "body": response.json()})
            print(f"    -> {event['type']} ({event['id']}) "
                  f"{response.status_code} {response.json()}")
        return applied

    def pump(
        self, *, expect: tuple[str, ...] = (), timeout: int = 60, label: str = ""
    ) -> list[dict[str, Any]]:
        """Drain events, waiting for the ones this step is supposed to produce.

        Stripe creates events asynchronously, so a drain immediately after an API
        call routinely sees nothing. Polling until the expected types arrive is
        what makes the assertions that follow meaningful rather than racy.
        """
        deadline = time.time() + timeout
        applied: list[dict[str, Any]] = []
        seen: set[str] = set()
        while True:
            batch = self._drain()
            applied.extend(batch)
            seen.update(a["event"]["type"] for a in batch)
            if set(expect) <= seen or time.time() >= deadline:
                break
            time.sleep(3)
        missing = sorted(set(expect) - seen)
        if missing:
            print(f"    !! timed out waiting for {missing} ({label})")
        elif not applied:
            print(f"    -> no new events for {label}")
        return applied

    # --- Stripe fixtures ----------------------------------------------------

    def new_clock(self) -> str:
        clock = self.stripe.test_helpers.TestClock.create(
            frozen_time=int(time.time()), name=f"osmos-e2e-{uuid.uuid4().hex[:6]}"
        )
        self.clocks.append(clock["id"])
        return clock["id"]

    def advance(self, clock_id: str, to_ts: int) -> None:
        self.stripe.test_helpers.TestClock.advance(clock_id, frozen_time=to_ts)
        for _ in range(120):
            clock = self.stripe.test_helpers.TestClock.retrieve(clock_id)
            if clock["status"] == "ready":
                return
            if clock["status"] == "internal_failure":
                raise RuntimeError(f"test clock {clock_id} failed to advance")
            time.sleep(2)
        raise RuntimeError(f"test clock {clock_id} did not become ready")

    def set_card(self, customer_id: str, token: str) -> str:
        pm = self.stripe.PaymentMethod.attach(token, customer=customer_id)
        self.stripe.Customer.modify(
            customer_id, invoice_settings={"default_payment_method": pm["id"]}
        )
        return pm["id"]

    # --- Osmos fixtures -----------------------------------------------------

    def new_org(self, name: str, members: int = 1) -> dict[str, Any]:
        """A throwaway workspace with `members` people in it."""
        tag = uuid.uuid4().hex[:8]
        owner = self.store.projects.create_user(f"owner-{tag}@osmos.test", "Owner")
        org = self.store.orgs.create(name, owner)
        project = self.store.projects.create_project(
            f"{name} context", owner_user_id=owner
        )
        self.store.orgs.attach_project(org["id"], project.id)
        extra = []
        for i in range(members - 1):
            uid = self.store.projects.create_user(
                f"member{i}-{tag}@osmos.test", f"Member {i}"
            )
            self.store.orgs.add_member(org["id"], uid, "member")
            extra.append(uid)
        return {
            "id": org["id"], "owner": owner, "extra": extra, "project_id": project.id
        }

    def db(self, org_id: str) -> dict[str, Any]:
        return self.store.billing.get(org_id) or {}

    # --- signup -------------------------------------------------------------

    def signup(self, org: dict[str, Any], *, interval: str, clock: str | None = None):
        """Run a real upgrade as far as Stripe allows without a browser.

        `service.start_checkout` is called for real, so the seat quantity, price,
        and metadata on the session are the ones the product would send. The
        session cannot then be *completed* headlessly, so the subscription is
        created directly with the session's own parameters and the resulting
        `checkout.session.completed` envelope is synthesised around the real
        session and real subscription id.
        """
        from app.billing import service

        customer_id = service.ensure_customer(self.store, org["id"])
        if clock:
            # A customer must be created on the clock, so re-link the org to one
            # that is. Only the throwaway workspace is affected.
            self.stripe.Customer.delete(customer_id)
            fresh = self.stripe.Customer.create(
                name="Osmos e2e", test_clock=clock,
                metadata={"osmos_org_id": org["id"]},
            )
            customer_id = fresh["id"]
            self.store.billing.link_customer(org["id"], customer_id)
        self.our_customers.add(customer_id)
        self.set_card(customer_id, GOOD_CARD)

        started = service.start_checkout(
            self.store, org["id"], org["owner"],
            interval=interval, base_url="https://withosmos.com",
        )
        session_id = self._session_id(started)
        session = plain(self.stripe.checkout.Session.retrieve(session_id))

        from app.billing.plans import price_id

        subscription = self.stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id(interval), "quantity": started["seats"]}],
            metadata={"osmos_org_id": org["id"]},
        )
        # The envelope Stripe would have sent when the session completed.
        session["subscription"] = subscription["id"]
        session["status"] = "complete"
        session["payment_status"] = "paid"
        event = {
            "id": f"evt_{uuid.uuid4().hex}",
            "object": "event",
            "api_version": self.stripe.api_version,
            "created": int(time.time()),
            "livemode": False,
            "type": "checkout.session.completed",
            "data": {"object": session},
        }
        response = self.deliver(event)
        self.delivered.add(event["id"])
        print(f"    -> checkout.session.completed (synthesised) "
              f"{response.status_code} {response.json()}")
        self.pump(expect=("invoice.paid",), label="signup")
        return {
            "customer_id": customer_id,
            "subscription_id": subscription["id"],
            "session_id": session_id,
            "checkout_session": session,
            "checkout_event": event,
        }

    def _session_id(self, started: dict[str, Any]) -> str:
        """Recover the session id from the checkout URL our service returned."""
        # https://checkout.stripe.com/c/pay/cs_test_...#fidkd...
        tail = started["checkout_url"].split("/pay/")[-1]
        return tail.split("#")[0]

    def sub(self, subscription_id: str) -> dict[str, Any]:
        return plain(self.stripe.Subscription.retrieve(subscription_id))

    # --- teardown -----------------------------------------------------------

    def cleanup(self) -> None:
        print("\n=== cleanup " + "=" * 58)
        for clock_id in self.clocks:
            try:
                self.stripe.test_helpers.TestClock.delete(clock_id)
                print(f"  deleted test clock {clock_id} (and its customers)")
            except Exception as exc:  # noqa: BLE001
                print(f"  could not delete clock {clock_id}: {exc}")
        for customer_id in sorted(self.our_customers):
            try:
                self.stripe.Customer.delete(customer_id)
                print(f"  deleted customer {customer_id}")
            except Exception:  # noqa: BLE001
                pass  # already gone with its test clock
        # SQLite keeps the file open until the pool is closed, and Windows will
        # not unlink a file that still has a handle on it.
        self.store.engine.dispose()


# --- scenarios --------------------------------------------------------------


def scenario_monthly(h: Harness) -> dict[str, Any]:
    r = h.report
    r.begin("monthly signup, one seat")
    org = h.new_org("Monthly Co", members=1)
    live = h.signup(org, interval="month")

    row = h.db(org["id"])
    sub = h.sub(live["subscription_id"])
    r.check("stripe: quantity", item_of(sub)["quantity"], 1)
    r.check("stripe: interval", item_of(sub)["price"]["recurring"]["interval"], "month")
    r.check("stripe: status", sub["status"], "active")
    r.check("db: plan", row["plan"], "pro")
    r.check("db: subscription_status", row["subscription_status"], "active")
    r.check("db: billable_seats", row["billable_seats"], 1)
    r.check("db: billing_interval", row["billing_interval"], "month")
    r.check("db: cancel_at_period_end", row["cancel_at_period_end"], 0)
    r.check("db: payment_failed_at", row["payment_failed_at"], None)
    r.truthy("db: current_period_end recorded", row["current_period_end"])
    r.check("effective plan", h.store.billing.effective_plan(org["id"]).name, "pro")
    return {"org": org, **live}


def scenario_annual(h: Harness) -> dict[str, Any]:
    r = h.report
    r.begin("annual signup")
    org = h.new_org("Annual Co", members=1)
    live = h.signup(org, interval="year")

    row = h.db(org["id"])
    sub = h.sub(live["subscription_id"])
    r.check("stripe: interval", item_of(sub)["price"]["recurring"]["interval"], "year")
    r.check("stripe: unit amount", item_of(sub)["price"]["unit_amount"], 8400)
    r.check("db: billing_interval", row["billing_interval"], "year")
    r.check("db: plan", row["plan"], "pro")
    r.truthy("db: current_period_end recorded", row["current_period_end"])
    return {"org": org, **live}


def scenario_seats(h: Harness) -> dict[str, Any]:
    """Multi-seat signup, then growth (prorated) and shrink (not prorated)."""
    from app.billing import service

    r = h.report
    r.begin("multi-seat signup (3 seats)")
    org = h.new_org("Team Co", members=3)
    live = h.signup(org, interval="month")

    sub = h.sub(live["subscription_id"])
    row = h.db(org["id"])
    r.check("osmos computed seats", h.store.billing.billable_seats(org["id"]), 3)
    r.check("stripe: quantity", item_of(sub)["quantity"], 3)
    r.check("db: billable_seats", row["billable_seats"], 3)

    r.begin("add a seat — prorates immediately")
    before = len(h.stripe.Invoice.list(customer=live["customer_id"], limit=100)["data"])
    newcomer = h.store.projects.create_user(
        f"new-{uuid.uuid4().hex[:6]}@osmos.test", "Newcomer"
    )
    h.store.orgs.add_member(org["id"], newcomer, "member")
    pushed = service.sync_seats(h.store, org["id"], growing=True)
    h.pump(label="add seat")  # a prorated growth issues no invoice yet

    sub = h.sub(live["subscription_id"])
    row = h.db(org["id"])
    r.check("sync_seats returned", pushed, 4)
    r.check("stripe: quantity", item_of(sub)["quantity"], 4)
    r.check("db: billable_seats", row["billable_seats"], 4)
    preview = plain(h.stripe.Invoice.create_preview(
        customer=live["customer_id"], subscription=live["subscription_id"]
    ))
    prorations = [
        line for line in preview["lines"]["data"]
        if (line.get("parent") or {}).get("subscription_item_details", {})
        .get("proration")
    ]
    r.truthy("stripe: a proration line exists for the added seat", prorations)
    r.note("upcoming invoice total (cents)", preview["total"])
    r.check(
        "no immediate extra invoice was issued",
        len(h.stripe.Invoice.list(customer=live["customer_id"], limit=100)["data"]),
        before,
    )

    r.begin("remove a seat — access ends now, billing falls at renewal")
    h.store.orgs.remove_member(org["id"], newcomer)
    r.check(
        "removed member's access ended immediately",
        h.store.orgs.get_org_role(org["id"], newcomer),
        None,
    )
    invoices_before = len(
        h.stripe.Invoice.list(customer=live["customer_id"], limit=100)["data"]
    )
    pushed = service.sync_seats(h.store, org["id"], growing=False)
    h.pump(label="remove seat")  # a shrink must produce nothing billable

    sub = h.sub(live["subscription_id"])
    row = h.db(org["id"])
    r.check("sync_seats returned", pushed, 3)
    r.check("stripe: quantity back to", item_of(sub)["quantity"], 3)
    r.check("db: billable_seats", row["billable_seats"], 3)
    r.check(
        "no credit note or invoice was raised mid-cycle",
        len(h.stripe.Invoice.list(customer=live["customer_id"], limit=100)["data"]),
        invoices_before,
    )
    credits = h.stripe.CreditNote.list(customer=live["customer_id"], limit=10)["data"]
    r.check("no credit note issued", len(credits), 0)
    return {"org": org, **live}


def scenario_renewal_and_dunning(h: Harness) -> dict[str, Any]:
    """Renewal, a failed payment, the grace period, and a card update."""
    r = h.report
    r.begin("renewal on a test clock")
    clock = h.new_clock()
    org = h.new_org("Renewing Co", members=2)
    live = h.signup(org, interval="month", clock=clock)

    first_end = period_end_of(h.sub(live["subscription_id"]))
    row_before = h.db(org["id"])
    r.truthy("db: current_period_end before renewal", row_before["current_period_end"])

    h.advance(clock, first_end + 3600)
    h.pump(expect=("invoice.paid", "customer.subscription.updated"), label="renewal")
    sub = h.sub(live["subscription_id"])
    row = h.db(org["id"])
    second_end = period_end_of(sub)
    r.check("stripe: still active after renewal", sub["status"], "active")
    r.truthy("stripe: period rolled forward", second_end > first_end)
    r.check("db: plan still pro", row["plan"], "pro")
    r.check("db: payment_failed_at clear", row["payment_failed_at"], None)
    # SQLite hands back a naive datetime, and calling .timestamp() on one reads
    # it as local time. ensure_aware is how the rest of the app reads these.
    from app.db import ensure_aware

    r.truthy(
        "db: current_period_end followed the renewal",
        row["current_period_end"]
        and int(ensure_aware(row["current_period_end"]).timestamp()) == second_end,
    )
    r.note("db current_period_end", row["current_period_end"])

    r.begin("failed payment (4000000000000341) keeps access during grace")
    h.set_card(live["customer_id"], FAILING_CARD)
    h.advance(clock, period_end_of(h.sub(live["subscription_id"])) + 3600)
    h.pump(expect=("invoice.payment_failed",), label="failed payment")

    sub = h.sub(live["subscription_id"])
    row = h.db(org["id"])
    r.check("stripe: status", sub["status"], "past_due")
    r.truthy("db: payment_failed_at set", row["payment_failed_at"])
    r.check("db: plan still pro", row["plan"], "pro")
    r.check("db: subscription_status", row["subscription_status"], "past_due")
    r.check(
        "access retained during grace",
        h.store.billing.effective_plan(org["id"]).name,
        "pro",
    )
    r.check("in_grace_period", h.store.billing.in_grace_period(row), True)

    # The other half of the same invariant: once grace really has run out,
    # entitlement does drop. Shrinking the window is the only way to observe
    # that without waiting a fortnight.
    os.environ["SAC_BILLING_GRACE_DAYS"] = "0"
    try:
        r.check(
            "access ends once grace expires",
            h.store.billing.effective_plan(org["id"]).name,
            "free",
        )
    finally:
        os.environ.pop("SAC_BILLING_GRACE_DAYS", None)
    r.check(
        "access restored when grace is back",
        h.store.billing.effective_plan(org["id"]).name,
        "pro",
    )

    r.begin("card update recovers the subscription")
    failed_at = row["payment_failed_at"]
    h.set_card(live["customer_id"], UPDATED_CARD)
    open_invoices = [
        inv for inv in h.stripe.Invoice.list(
            customer=live["customer_id"], status="open", limit=10
        )["data"]
    ]
    r.truthy("an open invoice is waiting", open_invoices)
    if open_invoices:
        h.stripe.Invoice.pay(open_invoices[0]["id"])
    h.pump(expect=("invoice.paid",), label="card update")

    sub = h.sub(live["subscription_id"])
    row = h.db(org["id"])
    r.check("stripe: recovered to active", sub["status"], "active")
    r.check("db: subscription_status", row["subscription_status"], "active")
    r.check("db: payment_failed_at cleared", row["payment_failed_at"], None)
    r.note("was failing since", failed_at)
    r.check("effective plan", h.store.billing.effective_plan(org["id"]).name, "pro")
    return {"org": org, "clock": clock, **live}


def scenario_cancel_and_downgrade(h: Harness, ctx: dict[str, Any]) -> None:
    """Cancel at period end, stay Pro until it arrives, then downgrade."""
    from app.billing import service

    r = h.report
    r.begin("cancellation — Pro until the period ends")
    org = ctx["org"]

    # Something worth keeping, to prove downgrade destroys nothing.
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    conn_id = h.store.projects.create_agent_connection(org["owner"], label="e2e")
    identity = h.store.resolve_identity(
        Principal(user_id=org["owner"], agent_connection_id=conn_id,
                  scopes=(READ_SCOPE, WRITE_SCOPE), label="e2e"),
        ctx["org"]["project_id"],
    )
    h.store.memories.remember(
        identity, scope="shared", kind="decision",
        summary="This memory must survive a downgrade.",
    )
    before = len(h.store.memories.list_memories(org["project_id"], org["owner"]))

    service.cancel(h.store, org["id"], org["owner"])
    h.pump(expect=("customer.subscription.updated",), label="cancel")

    sub = h.sub(ctx["subscription_id"])
    row = h.db(org["id"])
    r.check("stripe: cancel_at_period_end", sub["cancel_at_period_end"], True)
    r.check("stripe: still active", sub["status"], "active")
    r.check("db: cancel_at_period_end", row["cancel_at_period_end"], 1)
    r.check("db: plan still pro", row["plan"], "pro")
    r.check(
        "still entitled until period end",
        h.store.billing.effective_plan(org["id"]).name,
        "pro",
    )
    r.truthy("db: current_period_end known", row["current_period_end"])

    r.begin("downgrade to Free at period end")
    h.advance(ctx["clock"], period_end_of(sub) + 3600)
    h.pump(expect=("customer.subscription.deleted",), label="downgrade")

    sub = h.sub(ctx["subscription_id"])
    row = h.db(org["id"])
    r.check("stripe: subscription canceled", sub["status"], "canceled")
    r.check("db: plan", row["plan"], "free")
    r.check("db: subscription_status", row["subscription_status"], "canceled")
    r.check("effective plan", h.store.billing.effective_plan(org["id"]).name, "free")
    r.check(
        "downgrade deleted no memories",
        len(h.store.memories.list_memories(org["project_id"], org["owner"])),
        before,
    )
    r.check(
        "downgrade deleted no contexts",
        h.store.billing.usage_counts(org["id"])["contexts"],
        1,
    )
    r.truthy("stripe customer id kept for history", row["stripe_customer_id"])


def scenario_delivery_semantics(h: Harness, ctx: dict[str, Any]) -> None:
    """Retries, duplicates, and failing closed."""
    r = h.report
    r.begin("duplicate and retried deliveries")
    org = ctx["org"]

    # A real subscription.updated for this workspace, replayed.
    sub = h.sub(ctx["subscription_id"])
    event = {
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "api_version": h.stripe.api_version,
        "created": int(time.time()),
        "livemode": False,
        "type": "customer.subscription.updated",
        "data": {"object": sub},
    }
    first = h.deliver(event)
    row_after_first = h.db(org["id"])
    second = h.deliver(event)
    third = h.deliver(event)
    row_after_third = h.db(org["id"])

    r.check("first delivery status", first.status_code, 200)
    r.truthy("first delivery handled", first.json().get("handled"))
    r.check("second delivery status", second.status_code, 200)
    r.check("duplicate recognised", second.json().get("duplicate"), True)
    r.check("third delivery also duplicate", third.json().get("duplicate"), True)
    r.check(
        "state unchanged by duplicates",
        {k: row_after_third[k] for k in
         ("plan", "billable_seats", "subscription_status", "cancel_at_period_end")},
        {k: row_after_first[k] for k in
         ("plan", "billable_seats", "subscription_status", "cancel_at_period_end")},
    )

    r.begin("every already-delivered real event replayed once more")
    replayed_ok = True
    snapshot = dict(h.db(org["id"]))
    for event_id in list(h.delivered)[:25]:
        try:
            original = plain(h.stripe.Event.retrieve(event_id))
        except Exception:  # noqa: BLE001 - synthesised events are not in Stripe
            continue
        again = h.deliver(original)
        if again.status_code != 200 or not (
            again.json().get("duplicate") or again.json().get("ignored")
        ):
            replayed_ok = False
            print(f"    !! replay of {event_id} -> {again.status_code} {again.text}")
    r.truthy("all real events replay as duplicates", replayed_ok)
    r.check("workspace state untouched by the replay", dict(h.db(org["id"])), snapshot)

    r.begin("fails closed")
    bad = h.deliver({"id": "evt_forged", "type": "checkout.session.completed",
                     "data": {"object": {"id": "cs_forged"}}}, secret="whsec_wrong")
    r.check("a forged signature is rejected", bad.status_code, 400)

    real_secret = os.environ.pop("STRIPE_WEBHOOK_SECRET")
    try:
        unsigned = h.deliver(
            {"id": "evt_nosecret", "type": "checkout.session.completed",
             "data": {"object": {"id": "cs_x"}}},
            secret="anything",
        )
        r.check("no signing secret configured -> refused", unsigned.status_code, 400)
    finally:
        os.environ["STRIPE_WEBHOOK_SECRET"] = real_secret

    r.begin("customer cannot set their own seat count")
    tampered = h.sub(ctx["subscription_id"])
    item_of(tampered)["quantity"] = 999
    forged_event = {
        "id": f"evt_{uuid.uuid4().hex}", "object": "event",
        "api_version": h.stripe.api_version, "created": int(time.time()),
        "livemode": False, "type": "customer.subscription.updated",
        "data": {"object": tampered},
    }
    h.deliver(forged_event)
    # Whatever Stripe claims, the count Osmos computes from org_members is
    # unaffected — it is derived from our own table, so nothing a customer can
    # edit in Stripe's portal can move it. That is the direction of authority the
    # whole seat design depends on.
    r.check(
        "osmos still computes seats from membership",
        h.store.billing.billable_seats(org["id"]),
        len(h.store.orgs.list_members(org["id"])),
    )
    r.note("seats Osmos believes", h.store.billing.billable_seats(org["id"]))


# --- entry point ------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(REPO / "scratch_stripe_e2e.db"))
    parser.add_argument("--keep", action="store_true",
                        help="leave the Stripe objects and scratch database behind")
    args = parser.parse_args()

    for required in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                     "STRIPE_PRO_MONTHLY_PRICE_ID", "STRIPE_PRO_ANNUAL_PRICE_ID"):
        if not os.getenv(required, "").strip():
            print(f"{required} is not set", file=sys.stderr)
            return 2
    if not os.environ["STRIPE_SECRET_KEY"].startswith("sk_test"):
        print("refusing to run against a live key", file=sys.stderr)
        return 2

    h = Harness(args.db)
    try:
        scenario_monthly(h)
        scenario_annual(h)
        scenario_seats(h)
        ctx = scenario_renewal_and_dunning(h)
        scenario_cancel_and_downgrade(h, ctx)
        scenario_delivery_semantics(h, ctx)
    finally:
        if not args.keep:
            h.cleanup()
            Path(args.db).unlink(missing_ok=True)
    return h.report.summary()


if __name__ == "__main__":
    sys.exit(main())
