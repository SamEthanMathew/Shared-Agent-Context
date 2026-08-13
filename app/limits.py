"""Quotas, verification gates, and fixed-window rate limiting.

Multi-tenant safety: one account must not be able to exhaust the database or
brute-force an endpoint. Counters live in the `rate_events` table — sufficient
at this scale and one less moving part than Redis.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from .db import rate_events, utcnow
from .errors import ConflictError, ForbiddenError

# --- quotas -----------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


MAX_CONTEXTS_PER_USER = _int_env("SAC_MAX_CONTEXTS_PER_USER", 50)
MAX_MEMBERS_PER_CONTEXT = _int_env("SAC_MAX_MEMBERS_PER_CONTEXT", 50)
MAX_MEMORIES_PER_CONTEXT = _int_env("SAC_MAX_MEMORIES_PER_CONTEXT", 50_000)
MAX_SUMMARY_CHARS = _int_env("SAC_MAX_SUMMARY_CHARS", 2_000)
MAX_DETAILS_CHARS = _int_env("SAC_MAX_DETAILS_CHARS", 20_000)
MAX_TAGS = _int_env("SAC_MAX_TAGS", 25)
MAX_TAG_CHARS = _int_env("SAC_MAX_TAG_CHARS", 60)


def enforce_quota(store, current: int, limit: int, noun: str) -> None:
    """Raise a clear error rather than letting a limit surface as a 500."""
    if current >= limit:
        raise ConflictError(f"limit reached: at most {limit} {noun} allowed")


def require_verified(store, user_id: str, action: str) -> None:
    """Unverified accounts may read, but not create or accept."""
    if os.getenv("SAC_REQUIRE_VERIFIED_EMAIL", "1") not in ("1", "true", "True"):
        return
    if not store.auth.is_email_verified(user_id):
        raise ForbiddenError(
            f"verify your email address before you {action}"
        )


# --- rate limiting ----------------------------------------------------------


def client_ip(request) -> str:
    """The caller's address, trusting Render's proxy header when present.

    Shared by the HTML forms and the middleware in app/main.py so both bucket
    the same caller identically — two implementations would drift, and a
    mismatched key silently halves the effective limit.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Fixed-window counter keyed by an arbitrary string."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _window(self, seconds: int) -> datetime:
        now = utcnow()
        epoch = int(now.timestamp())
        return datetime.fromtimestamp(epoch - (epoch % seconds), tz=timezone.utc)

    def hit(self, key: str, limit: int, per_seconds: int) -> bool:
        """Count one event. Returns False when the limit is exceeded."""
        window = self._window(per_seconds)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(rate_events.c.count).where(
                    rate_events.c.key == key,
                    rate_events.c.window_start == window,
                )
            ).first()
            if row is None:
                conn.execute(
                    rate_events.insert().values(
                        key=key, window_start=window, count=1
                    )
                )
                return True
            # Index access, not row.count — the column name collides with the
            # tuple method of the same name.
            count = int(row[0]) + 1
            conn.execute(
                update(rate_events)
                .where(
                    rate_events.c.key == key,
                    rate_events.c.window_start == window,
                )
                .values(count=count)
            )
            return count <= limit

    def purge_older_than(self, age: timedelta = timedelta(days=1)) -> None:
        from sqlalchemy import delete

        cutoff = utcnow() - age
        with self.engine.begin() as conn:
            conn.execute(
                delete(rate_events).where(rate_events.c.window_start < cutoff)
            )


# Per-endpoint budgets: (limit, window seconds).
LIMITS: dict[str, tuple[int, int]] = {
    "login": (10, 300),
    "signup": (5, 3600),
    "forgot": (5, 3600),
    "invite_accept": (20, 3600),
    "token": (60, 300),
    "register": (10, 3600),
    "tool_call": (600, 60),
}
