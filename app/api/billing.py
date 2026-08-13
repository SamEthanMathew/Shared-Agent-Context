"""Billing HTTP surface.

The webhook lives here rather than under ``/v1`` on purpose. ``/v1`` is
authenticated by bearer token or session cookie and guarded by CSRF; a Stripe
webhook has neither and is authenticated by signature instead. Routing it
through the same middleware would mean either weakening that middleware or
fighting it, and both are worse than one clearly-separate route.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..billing import service
from ..billing import stripe_client, webhook
from ..errors import SACError, ValidationError
from ..runtime import get_store

router = APIRouter()


def _base_url() -> str:
    return (
        os.getenv("SAC_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
    ).rstrip("/")


# --- the webhook ------------------------------------------------------------


@router.post("/api/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request) -> JSONResponse:
    """Receive an event from Stripe.

    Reads the raw body, because signature verification is over exact bytes —
    re-serialising parsed JSON would change them and every signature would fail.

    Status codes are the control channel for Stripe's retries, so they are
    chosen deliberately: 400 for a bad signature (never retry, it will never
    become valid), 200 for anything handled or safely ignored, and 500 only when
    a retry might genuinely succeed.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = stripe_client.verify_webhook(payload, signature)
    except ValidationError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except SACError as exc:
        # Not configured. Answer 400 so Stripe stops rather than retrying into a
        # deployment that cannot ever process it.
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    try:
        result = webhook.handle(get_store(), event)
    except Exception as exc:  # noqa: BLE001
        # Left unfinished by the handler, so Stripe's retry will be processed.
        return JSONResponse(
            status_code=500, content={"detail": f"handler failed: {exc}"[:300]}
        )
    return JSONResponse(result)


# --- workspace billing (session-authenticated, under /v1) -------------------

v1 = APIRouter(prefix="/v1")


@v1.get("/orgs/{org_id}/billing", operation_id="get_billing")
def get_billing(org_id: str, request: Request) -> dict[str, Any]:
    """Plan, seats, usage against limits, and subscription state."""
    from .rest import _principal

    return service.summary(get_store(), org_id, _principal(request).user_id)


@v1.post("/orgs/{org_id}/billing/checkout", operation_id="start_checkout")
def start_checkout(
    org_id: str, request: Request, interval: str = "month"
) -> dict[str, Any]:
    """Begin an upgrade. Seats come from membership, never from the caller."""
    from .rest import _principal

    return service.start_checkout(
        get_store(),
        org_id,
        _principal(request).user_id,
        interval=interval,
        base_url=_base_url() or str(request.base_url).rstrip("/"),
    )


@v1.post("/orgs/{org_id}/billing/portal", operation_id="billing_portal")
def billing_portal(org_id: str, request: Request) -> dict[str, Any]:
    """A link into Stripe's portal for cards, invoices, and cancellation."""
    from .rest import _principal

    url = service.portal_url(
        get_store(),
        org_id,
        _principal(request).user_id,
        base_url=_base_url() or str(request.base_url).rstrip("/"),
    )
    return {"ok": True, "portal_url": url}


@v1.post("/orgs/{org_id}/billing/cancel", operation_id="cancel_subscription")
def cancel_subscription(org_id: str, request: Request) -> dict[str, Any]:
    """Stop renewing. Pro continues until the paid period ends."""
    from .rest import _principal

    return service.cancel(get_store(), org_id, _principal(request).user_id)
