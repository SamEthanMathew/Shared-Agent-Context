"""What each plan entitles a workspace to, and how limits are enforced.

Two principles run through this module, and both are deliberate choices rather
than implementation details:

**The plan column is authoritative, not Stripe.** Entitlement is read from the
local `organisations.plan` column, which only webhooks move. A Stripe outage, a
slow API call, or a network blip must never be able to decide whether a paying
customer can use the thing they paid for.

**Exceeding a limit restricts; it never destroys.** A workspace that downgrades
keeps every context and every memory. What it loses is the ability to *add*
more, and read access to whatever sits beyond the free allowance — which is
recoverable the moment they upgrade again, because nothing was deleted. Billing
lapses are usually an expired card, not a decision to leave.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from ..errors import ConflictError

FREE = "free"
PRO = "pro"
ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class Plan:
    """One plan's entitlements. `None` means no limit."""

    name: str
    label: str
    max_contexts: int | None
    max_members: int | None
    max_agents: int | None
    max_memories_per_context: int | None
    # Monthly syncs. The one usage dimension Free bounds, because it is what
    # actually costs us money to serve.
    max_syncs_per_month: int | None

    def allows(self, feature: str, current: int) -> bool:
        limit = getattr(self, feature)
        return limit is None or current < limit


def _limit_env(name: str, default: int) -> int | None:
    """A Free-plan limit, overridable without a deploy.

    Deliberately settable: these numbers are a pricing hypothesis, not a fact,
    and the first time a real user hits one at an awkward moment you want to be
    able to move it in seconds rather than ship a release. `0` means unlimited.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return None if value <= 0 else value


PLANS: dict[str, Plan] = {
    FREE: Plan(
        name=FREE,
        label="Free",
        max_contexts=_limit_env("SAC_FREE_MAX_CONTEXTS", 1),
        max_members=_limit_env("SAC_FREE_MAX_MEMBERS", 3),
        max_agents=_limit_env("SAC_FREE_MAX_AGENTS", 3),
        max_memories_per_context=_limit_env("SAC_FREE_MAX_MEMORIES", 1_000),
        max_syncs_per_month=_limit_env("SAC_FREE_MAX_SYNCS", 500),
    ),
    PRO: Plan(
        name=PRO,
        label="Pro",
        max_contexts=None,
        max_members=None,
        max_agents=None,
        # Still bounded — this is the multi-tenant safety cap from app/limits.py,
        # not a commercial one. Nobody should be able to exhaust the database.
        max_memories_per_context=50_000,
        max_syncs_per_month=None,
    ),
    ENTERPRISE: Plan(
        name=ENTERPRISE,
        label="Enterprise",
        max_contexts=None,
        max_members=None,
        max_agents=None,
        max_memories_per_context=None,
        max_syncs_per_month=None,
    ),
}


def plan_for(name: str | None) -> Plan:
    """Resolve a plan name, defaulting to Free.

    Falls back rather than raising: an unrecognised value in the database should
    degrade to the safe plan, not take the request down.
    """
    return PLANS.get((name or FREE).strip().lower(), PLANS[FREE])


# --- pricing ----------------------------------------------------------------

# Per seat, in cents, so no float ever touches money.
PRO_MONTHLY_CENTS = 800
PRO_ANNUAL_CENTS = 8_400


def price_id(interval: str) -> str:
    """The configured Stripe price for a billing interval."""
    key = (
        "STRIPE_PRO_ANNUAL_PRICE_ID"
        if interval == "year"
        else "STRIPE_PRO_MONTHLY_PRICE_ID"
    )
    value = os.getenv(key, "").strip()
    if not value:
        raise ConflictError(
            f"billing is not configured on this deployment ({key} is unset)"
        )
    return value


def interval_for_price(price: str) -> str:
    """Reverse the mapping, so a webhook can record which interval was bought."""
    if price and price == os.getenv("STRIPE_PRO_ANNUAL_PRICE_ID", "").strip():
        return "year"
    return "month"


def founding_coupon() -> str | None:
    return os.getenv("STRIPE_FOUNDING_COUPON_ID", "").strip() or None


def billing_configured() -> bool:
    """Whether this deployment can sell anything.

    Everything degrades to Free when Stripe is not configured, so the product
    runs unchanged in development and in CI without a Stripe account.
    """
    return bool(os.getenv("STRIPE_SECRET_KEY", "").strip())


# --- grace period -----------------------------------------------------------


def grace_days() -> int:
    """How long service continues after a failed payment.

    A failed payment is almost always an expired card, not an intention to
    leave. Cutting access off the same day punishes the wrong thing and costs
    far more in goodwill than a fortnight of service costs to serve.
    """
    try:
        return int(os.getenv("SAC_BILLING_GRACE_DAYS", "14"))
    except ValueError:
        return 14


# --- enforcement ------------------------------------------------------------


def enforce(plan: Plan, feature: str, current: int, noun: str) -> None:
    """Refuse an addition that would exceed the plan, naming the way out.

    The error text matters: someone hitting a plan ceiling needs to know it is a
    plan ceiling and not a malfunction, so the message says which plan and what
    to do about it.
    """
    limit = getattr(plan, feature)
    if limit is not None and current >= limit:
        raise ConflictError(
            f"{plan.label} plan allows at most {limit} {noun}. "
            "Upgrade to Pro for more."
        )
