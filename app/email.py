"""Outbound email.

One small interface with two backends:

* ``console`` (default) logs the message instead of sending — used in dev and
  in the whole test suite, so tests never touch the network;
* ``resend``  posts to the Resend HTTP API when SAC_EMAIL_PROVIDER=resend and
  RESEND_API_KEY is set.

Swap in SES/Postmark/SMTP by adding one function here; nothing else changes.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger("sac.email")


@dataclass
class Email:
    to: str
    subject: str
    text: str


def _from_address() -> str:
    # The fallback keeps Resend's shared test sender, which only delivers to the
    # account owner's own address — a deployment that forgets SAC_EMAIL_FROM should
    # fail visibly to everyone else rather than quietly send as the wrong product.
    return os.getenv("SAC_EMAIL_FROM", "Osmos <onboarding@resend.dev>")


def _public_url() -> str:
    return (
        os.getenv("SAC_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
    ).rstrip("/")


def send(email: Email) -> bool:
    """Deliver a message. Returns True if it was handed to a provider.

    Never raises: a failure to send must not break signup or sharing. Callers
    surface the link in the UI as a fallback.
    """
    provider = os.getenv("SAC_EMAIL_PROVIDER", "console").strip().lower()
    if provider == "resend":
        api_key = os.getenv("RESEND_API_KEY", "")
        if not api_key:
            logger.warning("SAC_EMAIL_PROVIDER=resend but RESEND_API_KEY is unset")
        else:
            try:
                r = httpx.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "from": _from_address(),
                        "to": [email.to],
                        "subject": email.subject,
                        "text": email.text,
                    },
                    timeout=10,
                )
                if r.status_code < 300:
                    return True
                logger.error("resend rejected message: %s %s", r.status_code, r.text[:200])
            except httpx.HTTPError as exc:
                logger.error("resend request failed: %s", exc)
    # Message bodies carry verification tokens, reset tokens, and invite codes.
    # Only the explicit console backend (dev) prints them; if a real provider
    # was configured and failed, log metadata only so secrets never reach
    # production logs.
    if provider == "console":
        logger.info(
            "[email:console] to=%s subject=%s\n%s", email.to, email.subject, email.text
        )
    else:
        logger.error(
            "[email:%s] delivery failed; body withheld. to=%s subject=%s",
            provider, email.to, email.subject,
        )
    return False


# --- message templates ------------------------------------------------------


def send_verification(to: str, token: str) -> bool:
    link = f"{_public_url()}/auth/verify?token={token}"
    return send(Email(
        to=to,
        subject="Verify your Osmos email",
        text=(
            "Confirm your email address to finish setting up Osmos.\n\n"
            f"{link}\n\nThis link expires in 24 hours. If you didn't sign up, ignore this."
        ),
    ))


def send_password_reset(to: str, token: str) -> bool:
    link = f"{_public_url()}/auth/reset?token={token}"
    return send(Email(
        to=to,
        subject="Reset your Osmos password",
        text=(
            "Use this link to choose a new password.\n\n"
            f"{link}\n\nThis link expires in 1 hour. If you didn't request it, ignore this."
        ),
    ))


def send_invite(to: str, code: str, context_name: str, inviter: str, access: str) -> bool:
    link = f"{_public_url()}/invite/{code}"
    return send(Email(
        to=to,
        subject=f"{inviter} shared the context '{context_name}' with you",
        text=(
            f"{inviter} gave you {access} access to the shared context "
            f"'{context_name}' on Osmos — shared project memory for AI assistants.\n\n"
            f"{link}\n\n"
            "Open the link to join. This invite expires in 14 days."
        ),
    ))


def send_share_notice(to: str, context_name: str, inviter: str, access: str) -> bool:
    link = f"{_public_url()}/console"
    return send(Email(
        to=to,
        subject=f"{inviter} shared the context '{context_name}' with you",
        text=(
            f"{inviter} gave you {access} access to '{context_name}'.\n\n{link}\n\n"
            "Your connected AI clients will see it on their next sync."
        ),
    ))
