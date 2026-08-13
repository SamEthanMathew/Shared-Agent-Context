"""The only module that talks to Stripe.

Everything Stripe-shaped is confined here so the rest of the billing code can be
tested without a network, and so a change in Stripe's SDK touches one file.
Callers get plain dicts, never SDK objects.

The `stripe` package is imported lazily. A deployment with no Stripe
configuration must still boot and serve — Free is a pure application
entitlement, so the product is complete without an account.
"""
from __future__ import annotations

import os
from typing import Any

from ..errors import ConflictError, ValidationError


class StripeNotConfigured(ConflictError):
    """Raised when a billing action is attempted with no Stripe credentials."""


def _stripe():
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise StripeNotConfigured("billing is not configured on this deployment")
    try:
        import stripe as stripe_sdk
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise StripeNotConfigured("the stripe package is not installed") from exc
    stripe_sdk.api_key = secret
    return stripe_sdk


def is_test_mode() -> bool:
    """True while the configured key is a test key.

    Surfaced in the UI so nobody demonstrates a purchase flow believing real
    money moved, or the reverse.
    """
    return os.getenv("STRIPE_SECRET_KEY", "").strip().startswith("sk_test")


# --- customers --------------------------------------------------------------


def create_customer(*, name: str, email: str, org_id: str) -> str:
    """One customer per workspace. The org id travels in metadata so an event
    can be traced back even if our own linking row were lost."""
    stripe = _stripe()
    customer = stripe.Customer.create(
        name=name,
        email=email or None,
        metadata={"osmos_org_id": org_id},
    )
    return customer["id"]


# --- checkout ---------------------------------------------------------------


def create_checkout_session(
    *,
    customer_id: str,
    price: str,
    quantity: int,
    success_url: str,
    cancel_url: str,
    org_id: str,
    coupon: str | None = None,
) -> dict[str, Any]:
    """A subscription Checkout Session for a whole workspace.

    `adjustable_quantity` is deliberately absent: seat count is computed by
    Osmos from actual membership. Letting the customer type a number here would
    let them pay for three seats while ten people use the product.
    """
    if quantity < 1:
        raise ValidationError("a subscription needs at least one seat")
    stripe = _stripe()
    params: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": [{"price": price, "quantity": quantity}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        # Both, on purpose: client_reference_id is echoed on the session, and
        # subscription_data.metadata sticks to the subscription for the whole of
        # its life, so later events identify the workspace without a lookup.
        "client_reference_id": org_id,
        "metadata": {"osmos_org_id": org_id},
        "subscription_data": {"metadata": {"osmos_org_id": org_id}},
        # Stripe Tax is off until the company is actually registered somewhere.
        # Flipping this on is the whole change when that day comes.
        "automatic_tax": {"enabled": _tax_enabled()},
    }
    if coupon:
        params["discounts"] = [{"coupon": coupon}]
    session = stripe.checkout.Session.create(**params)
    return {"id": session["id"], "url": session["url"]}


def _tax_enabled() -> bool:
    return os.getenv("STRIPE_TAX_ENABLED", "").strip().lower() in ("1", "true", "yes")


# --- customer portal --------------------------------------------------------


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Stripe's own UI for cards, invoices, and cancellation.

    Seat quantity is not editable here. Where a portal configuration id is
    supplied it should be one with quantity updates switched off; without one,
    Stripe's default configuration is used and the seat count we push on every
    membership change corrects any drift.
    """
    stripe = _stripe()
    params: dict[str, Any] = {"customer": customer_id, "return_url": return_url}
    configuration = os.getenv("STRIPE_PORTAL_CONFIGURATION_ID", "").strip()
    if configuration:
        params["configuration"] = configuration
    return stripe.billing_portal.Session.create(**params)["url"]


# --- subscriptions ----------------------------------------------------------


def get_subscription(subscription_id: str) -> dict[str, Any]:
    return dict(_stripe().Subscription.retrieve(subscription_id))


def update_quantity(
    subscription_id: str, quantity: int, *, prorate: bool
) -> dict[str, Any]:
    """Change the billed seat count.

    Growing prorates immediately: they have the seats now, so they pay now.
    Shrinking does not — the seat is already paid for through the current
    period, and clawing it back mid-cycle is both fiddly and unfriendly. The
    smaller quantity simply takes effect at renewal.
    """
    stripe = _stripe()
    subscription = stripe.Subscription.retrieve(subscription_id)
    items = subscription["items"]["data"]
    if not items:
        raise ConflictError("subscription has no line items")
    updated = stripe.Subscription.modify(
        subscription_id,
        items=[{"id": items[0]["id"], "quantity": quantity}],
        proration_behavior="create_prorations" if prorate else "none",
    )
    return dict(updated)


def cancel_at_period_end(subscription_id: str) -> dict[str, Any]:
    """Stop renewing, but serve what has been paid for until it runs out."""
    return dict(
        _stripe().Subscription.modify(subscription_id, cancel_at_period_end=True)
    )


# --- webhooks ---------------------------------------------------------------


def verify_webhook(payload: bytes, signature: str) -> dict[str, Any]:
    """Parse a webhook only if it genuinely came from Stripe.

    Without this the endpoint is an unauthenticated way to grant any workspace a
    paid plan, so an unset signing secret is a hard failure rather than a
    permissive fallback.
    """
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not set")
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise ValidationError(f"invalid Stripe signature: {exc}") from exc
    return dict(event)


# --- one-time setup ---------------------------------------------------------


def ensure_catalogue() -> dict[str, str]:
    """Create the Osmos Pro product and its two seat prices, idempotently.

    Run once per Stripe mode. Returns the ids to put in the environment. Looks
    for an existing product by metadata first, so re-running does not create
    duplicates — a surprisingly easy way to end up billing two different prices.
    """
    stripe = _stripe()
    marker = {"osmos_catalogue": "pro"}

    # Walk every page, not just the first. Stripe caps a list response at 100,
    # so an account that sells anything else can push the Osmos product out of
    # sight — and the failure is a duplicate product with a duplicate pair of
    # prices, created silently, with customers split across the two.
    product = None
    for candidate in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        if (candidate.get("metadata") or {}).get("osmos_catalogue") == "pro":
            product = candidate
            break
    if product is None:
        product = stripe.Product.create(
            name="Osmos Pro",
            description=(
                "Shared project memory across AI agents. Billed per member."
            ),
            metadata=marker,
        )

    existing = list(
        stripe.Price.list(
            product=product["id"], active=True, limit=100
        ).auto_paging_iter()
    )

    def _find(interval: str, amount: int):
        for price in existing:
            recurring = price.get("recurring") or {}
            if (
                recurring.get("interval") == interval
                and price.get("unit_amount") == amount
                and price.get("currency") == "usd"
            ):
                return price
        return None

    monthly = _find("month", 800) or stripe.Price.create(
        product=product["id"],
        unit_amount=800,
        currency="usd",
        recurring={"interval": "month"},
        metadata=marker,
    )
    annual = _find("year", 8400) or stripe.Price.create(
        product=product["id"],
        unit_amount=8400,
        currency="usd",
        recurring={"interval": "year"},
        metadata=marker,
    )

    result = {
        "product_id": product["id"],
        "STRIPE_PRO_MONTHLY_PRICE_ID": monthly["id"],
        "STRIPE_PRO_ANNUAL_PRICE_ID": annual["id"],
    }

    if os.getenv("STRIPE_CREATE_FOUNDING_COUPON", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        coupon = stripe.Coupon.create(
            percent_off=25,
            duration="repeating",
            duration_in_months=12,
            name="Founding Teams",
            metadata=marker,
        )
        result["STRIPE_FOUNDING_COUPON_ID"] = coupon["id"]

    return result
