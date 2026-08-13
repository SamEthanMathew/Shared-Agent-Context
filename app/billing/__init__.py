"""Billing: plan entitlements, Stripe integration, and cost accounting.

The shape, in one paragraph: an Osmos **organisation is the billing workspace**.
One organisation is one Stripe customer with at most one subscription, whose
quantity is that organisation's billable seat count. Free needs no Stripe object
at all — it is purely an application entitlement — so the product runs complete
and unmodified on a deployment that has never heard of Stripe.

Seat count is computed by Osmos and pushed to Stripe, never the reverse. Letting
a customer edit quantity in the Stripe portal would let them pay for three seats
while using ten.
"""
from .plans import (  # noqa: F401
    ENTERPRISE,
    FREE,
    PRO,
    Plan,
    billing_configured,
    enforce,
    grace_days,
    plan_for,
)
