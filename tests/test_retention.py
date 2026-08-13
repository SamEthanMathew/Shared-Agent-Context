"""Data retention.

Nothing in SAC deleted anything before this, so the risk in adding a reaper is
not that it fails to delete — it is that it deletes something it shouldn't. These
tests are weighted accordingly: most of them assert what *survives*.

Two policy decisions are pinned here because they are judgement calls, not
mechanics: sync records age out (they enumerate one person's private memory, so
keeping them forever is a privacy cost), and the audit trail does not (it is the
record you need to answer a security question about the past).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import (
    auth_transactions,
    authorization_codes,
    context_snapshots,
    email_tokens,
    login_sessions,
    oauth_tokens,
    rate_events,
    utcnow,
)
from app.retention import preview, reap


def _count(engine, table) -> int:
    from sqlalchemy import func, select

    with engine.begin() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())


def _snapshot(seed, age_days: float, task="a sync"):
    """A sync record backdated by hand — the store always stamps 'now'."""
    from sqlalchemy import update

    from app.context import compile_context

    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.alice_user_id, f"chat-{age_days}-{task}"
    )
    out = compile_context(seed.store, seed.alice, session, task)
    when = utcnow() - timedelta(days=age_days)
    with seed.store.engine.begin() as conn:
        conn.execute(
            update(context_snapshots)
            .where(context_snapshots.c.id == out["snapshot_id"])
            .values(created_at=when)
        )
    return out["snapshot_id"]


# --- sync records age out ---------------------------------------------------


def test_old_sync_records_are_deleted(seed):
    _snapshot(seed, age_days=120)
    assert _count(seed.store.engine, context_snapshots) == 1
    report = reap(seed.store.engine)
    assert _count(seed.store.engine, context_snapshots) == 0
    assert report.deleted["context_snapshots"] == 1


def test_recent_sync_records_survive(seed):
    """The whole point is answering "what did the agent know" for a while."""
    keep = _snapshot(seed, age_days=10)
    reap(seed.store.engine)
    assert seed.store.snapshots.get(keep) is not None


def test_the_retention_window_is_configurable(seed, monkeypatch):
    monkeypatch.setenv("SAC_RETENTION_DAYS_SNAPSHOTS", "5")
    _snapshot(seed, age_days=10)
    reap(seed.store.engine)
    assert _count(seed.store.engine, context_snapshots) == 0


def test_a_record_exactly_inside_the_window_survives(seed):
    """Off-by-one at the boundary would silently shorten the window."""
    _snapshot(seed, age_days=89)
    reap(seed.store.engine)
    assert _count(seed.store.engine, context_snapshots) == 1


# --- the audit trail is kept ------------------------------------------------


def test_the_audit_trail_is_never_reaped(seed):
    """Who shared what with whom outlives the sync records."""
    from sqlalchemy import update

    from app.db import audit_events

    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Audited."
    )
    before = _count(seed.store.engine, audit_events)
    assert before > 0

    # Age every audit row well past any other policy's cutoff.
    with seed.store.engine.begin() as conn:
        conn.execute(
            update(audit_events).values(created_at=utcnow() - timedelta(days=3650))
        )

    reap(seed.store.engine)
    assert _count(seed.store.engine, audit_events) == before


def test_memories_are_never_reaped(seed):
    """Retention is about telemetry, not about the product's actual content."""
    from app.db import memories

    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Still here."
    )
    reap(seed.store.engine)
    assert _count(seed.store.engine, memories) >= 1


# --- expired auth machinery -------------------------------------------------


def _expire(engine, table, column, days: float = 1):
    from sqlalchemy import update

    with engine.begin() as conn:
        conn.execute(update(table).values(**{column: utcnow() - timedelta(days=days)}))


def test_expired_oauth_transactions_and_codes_go(seed):
    auth = seed.store.auth
    txn = auth.create_transaction(
        client_id="c", redirect_uri="https://x/cb", redirect_uri_provided=True,
        scopes=["sac.read"], code_challenge="ch", code_challenge_method="S256",
        state="s", resource="https://x/mcp",
    )
    assert txn
    _expire(seed.store.engine, auth_transactions, "expires_at")
    reap(seed.store.engine)
    assert _count(seed.store.engine, auth_transactions) == 0


def test_unexpired_transactions_survive(seed):
    """A live OAuth handshake must not be reaped mid-flight."""
    auth = seed.store.auth
    txn = auth.create_transaction(
        client_id="c", redirect_uri="https://x/cb", redirect_uri_provided=True,
        scopes=["sac.read"], code_challenge="ch", code_challenge_method="S256",
        state="s", resource="https://x/mcp",
    )
    reap(seed.store.engine)
    assert auth.get_transaction(txn) is not None


def test_expired_login_sessions_go_but_live_ones_stay(seed):
    auth = seed.store.auth
    live = auth.create_login_session(seed.alice_user_id)
    stale = auth.create_login_session(seed.bob_user_id)

    from sqlalchemy import update

    from app.auth.store import sha256

    with seed.store.engine.begin() as conn:
        conn.execute(
            update(login_sessions)
            .where(login_sessions.c.sid_hash == sha256(stale))
            .values(expires_at=utcnow() - timedelta(days=1))
        )

    reap(seed.store.engine)
    assert auth.get_login_user(live) == seed.alice_user_id
    assert auth.get_login_user(stale) is None
    assert _count(seed.store.engine, login_sessions) == 1


def test_expired_email_tokens_go(seed):
    seed.store.auth.create_email_token(
        seed.alice_user_id, "verify", timedelta(seconds=-1)
    )
    assert _count(seed.store.engine, email_tokens) == 1
    reap(seed.store.engine)
    assert _count(seed.store.engine, email_tokens) == 0


def test_rate_counters_are_purged(seed):
    from app.limits import RateLimiter

    limiter = RateLimiter(seed.store.engine)
    limiter.hit("login:1.2.3.4", 10, 300)
    assert _count(seed.store.engine, rate_events) == 1

    from sqlalchemy import update

    with seed.store.engine.begin() as conn:
        conn.execute(
            update(rate_events).values(window_start=utcnow() - timedelta(days=2))
        )
    reap(seed.store.engine)
    assert _count(seed.store.engine, rate_events) == 0


def test_todays_rate_counters_survive(seed):
    """Purging the live window would reset everyone's limit."""
    from app.limits import RateLimiter

    RateLimiter(seed.store.engine).hit("login:1.2.3.4", 10, 300)
    reap(seed.store.engine)
    assert _count(seed.store.engine, rate_events) == 1


# --- operational properties -------------------------------------------------


def test_reaping_is_idempotent(seed):
    _snapshot(seed, age_days=120)
    first = reap(seed.store.engine)
    second = reap(seed.store.engine)
    assert first.total >= 1
    assert second.total == 0


def test_reaping_an_empty_database_is_a_no_op(seed):
    report = reap(seed.store.engine)
    assert report.total == 0
    assert report.lines() == ["nothing to delete"]


def test_batching_handles_more_rows_than_one_batch(seed, monkeypatch):
    """The first run against a long-neglected table must not need one huge
    transaction, so deletes page. Prove the paging loop terminates and clears
    everything."""
    import app.retention as retention

    monkeypatch.setattr(retention, "BATCH", 3)
    for n in range(10):
        _snapshot(seed, age_days=200, task=f"old-{n}")
    assert _count(seed.store.engine, context_snapshots) == 10

    report = retention.reap(seed.store.engine)
    assert _count(seed.store.engine, context_snapshots) == 0
    assert report.deleted["context_snapshots"] == 10


def test_preview_reports_without_deleting(seed):
    """Worth having before the first production run."""
    _snapshot(seed, age_days=120)
    report = preview(seed.store.engine)
    assert report.deleted["context_snapshots"] == 1
    # Nothing actually went.
    assert _count(seed.store.engine, context_snapshots) == 1


def test_preview_and_reap_agree(seed):
    _snapshot(seed, age_days=120)
    seed.store.auth.create_email_token(
        seed.alice_user_id, "verify", timedelta(seconds=-1)
    )
    planned = preview(seed.store.engine)
    actual = reap(seed.store.engine)
    for table, count in planned.deleted.items():
        assert actual.deleted.get(table, 0) == count, table
