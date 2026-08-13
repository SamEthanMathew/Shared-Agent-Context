"""Provision the Stripe side of a deployment: catalogue plus webhook endpoint.

    STRIPE_SECRET_KEY=sk_test_... python scripts/stripe_provision.py

Idempotent, and safe to re-run: the catalogue is matched by metadata and the
webhook endpoint by URL, so a second run creates nothing.

One wrinkle is worth knowing before you run this in production. **Stripe returns
a webhook signing secret only in the response that creates the endpoint.** It is
absent from every subsequent retrieve or list, and there is no API to roll it. So
if the secret is lost, the only way to get a working one from the API is to
delete the endpoint and create it again — which is what ``--rotate`` does, and
why it is opt-in rather than the default. Capture the secret on first run.
"""
from __future__ import annotations

import argparse
import os
import sys

WEBHOOK_URL = "https://withosmos.com/api/webhooks/stripe"

# Exactly the events app/billing/webhook.py knows how to apply. Subscribing to
# more would mean Stripe retrying deliveries we answer 200 to but do nothing
# with, which makes a real delivery failure harder to see in the dashboard.
EVENTS = [
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
]


def _find_endpoint(stripe, url: str):
    for endpoint in stripe.WebhookEndpoint.list(limit=100)["data"]:
        if endpoint["url"] == url:
            return endpoint
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=WEBHOOK_URL)
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="delete and recreate the endpoint to obtain a fresh signing secret",
    )
    args = parser.parse_args()

    if not os.getenv("STRIPE_SECRET_KEY", "").strip():
        print("STRIPE_SECRET_KEY is not set", file=sys.stderr)
        return 2

    from app.billing.stripe_client import _stripe, ensure_catalogue, is_test_mode

    stripe = _stripe()
    mode = "TEST" if is_test_mode() else "LIVE"
    print(f"[stripe] {mode} mode, api version {stripe.api_version}")

    catalogue = ensure_catalogue()
    print(f"[stripe] product {catalogue.pop('product_id')}")

    endpoint = _find_endpoint(stripe, args.url)
    if endpoint is not None and args.rotate:
        print(f"[stripe] deleting {endpoint['id']} to rotate its signing secret")
        stripe.WebhookEndpoint.delete(endpoint["id"])
        endpoint = None

    if endpoint is None:
        endpoint = stripe.WebhookEndpoint.create(
            url=args.url,
            enabled_events=EVENTS,
            # Pin the endpoint to the version the SDK sends, so the objects in a
            # delivered event have the same shape as the ones a direct API call
            # returns. Leaving it unpinned means the two can drift apart at a
            # Stripe release and only one of the two code paths breaks.
            api_version=stripe.api_version,
            description="Osmos billing webhook",
            metadata={"osmos": "primary"},
        )
        print(f"[stripe] created endpoint {endpoint['id']} -> {endpoint['url']}")
        print("\nSet these in your environment:\n")
        for key, value in catalogue.items():
            print(f"  {key}={value}")
        print(f"  STRIPE_WEBHOOK_SECRET={endpoint['secret']}")
        return 0

    missing = sorted(set(EVENTS) - set(endpoint["enabled_events"]))
    if missing:
        stripe.WebhookEndpoint.modify(endpoint["id"], enabled_events=EVENTS)
        print(f"[stripe] added missing events to {endpoint['id']}: {missing}")

    print(f"[stripe] endpoint {endpoint['id']} already exists ({endpoint['status']})")
    print("[stripe] its signing secret is not readable via the API; --rotate to reset")
    print("\nSet these in your environment:\n")
    for key, value in catalogue.items():
        print(f"  {key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
