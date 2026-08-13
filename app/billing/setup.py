"""One-time Stripe catalogue setup.

    STRIPE_SECRET_KEY=sk_test_... python -m app.billing.setup

Idempotent: it looks for an existing Osmos product by metadata before creating
one, so re-running does not quietly leave you billing two different prices.
Prints the ids to put in the environment.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    from .stripe_client import ensure_catalogue, is_test_mode

    if not os.getenv("STRIPE_SECRET_KEY", "").strip():
        print("STRIPE_SECRET_KEY is not set", file=sys.stderr)
        return 2

    mode = "TEST" if is_test_mode() else "LIVE"
    print(f"[stripe] {mode} mode")
    if mode == "LIVE":
        print("[stripe] this will create real products. Ctrl-C within 5s to abort.")
        import time

        time.sleep(5)

    result = ensure_catalogue()
    print(f"[stripe] product: {result.pop('product_id')}")
    print("\nSet these in your environment:\n")
    for key, value in result.items():
        print(f"  {key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
