"""Data retention: delete what has expired or aged out.

Nothing in SAC deleted anything before this. Every login attempt, every OAuth
handshake, and — worst — every agent turn wrote a row that lived forever. Sync
records are the fastest-growing table in the system by a wide margin, since there
is one per turn and each carries JSON manifests, so that table is what fills the
disk first.

Two decisions are encoded here, and both are deliberate:

**Sync records age out; the audit trail does not.** A sync record answers "what
exactly did the agent know when it said that", which is worth 90 days and not
worth forever — and it enumerates one person's private memory, so keeping it
indefinitely is a privacy cost, not just a storage one. The audit trail is who
shared what with whom: small, append-only, and the thing you actually need when
answering a security question about the past.

**Deletes are batched.** The first run against a table that has been growing for
months could otherwise hold one enormous transaction, taking locks and bloating
WAL on a small instance. Bounded batches make the job interruptible and safe to
run while the service is serving.

The functions here take a live engine and are safe to run concurrently with the
web process and with themselves — every statement is an unqualified delete of
rows that are already unreachable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine

from .db import (
    agent_connections,
    auth_transactions,
    authorization_codes,
    context_snapshots,
    email_tokens,
    login_sessions,
    oauth_clients,
    oauth_tokens,
    utcnow,
)
from .limits import RateLimiter

# How many rows one statement may remove. Small enough that a first run against a
# long-neglected table stays interruptible; large enough that catching up does not
# take all night.
BATCH = 5_000

# Passes are capped so a single invocation cannot run unbounded if rows are being
# created as fast as they are deleted. The next scheduled run continues.
MAX_BATCHES = 200


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def snapshot_retention_days() -> int:
    return _int_env("SAC_RETENTION_DAYS_SNAPSHOTS", 90)


def abandoned_client_grace_days() -> int:
    """How long an unused client registration is given to be completed.

    Generous on purpose: a legitimate registration is followed by consent within
    seconds, so a day means only genuinely abandoned rows are removed, and never
    one mid-handshake.
    """
    return _int_env("SAC_RETENTION_DAYS_ABANDONED_CLIENTS", 1)


def revoked_token_retention_days() -> int:
    """Revoked refresh tokens are kept a while: "when was this cut off" is a
    question worth being able to answer after the fact."""
    return _int_env("SAC_RETENTION_DAYS_REVOKED_TOKENS", 30)


@dataclass
class ReapReport:
    deleted: dict[str, int] = field(default_factory=dict)

    def add(self, table: str, count: int) -> None:
        if count:
            self.deleted[table] = self.deleted.get(table, 0) + count

    @property
    def total(self) -> int:
        return sum(self.deleted.values())

    def lines(self) -> list[str]:
        if not self.deleted:
            return ["nothing to delete"]
        return [f"{table}: {n}" for table, n in sorted(self.deleted.items())]


def _delete_batched(engine: Engine, table, predicate, pk_columns) -> int:
    """Delete rows matching `predicate`, BATCH at a time.

    Selects a page of primary keys and deletes exactly those, rather than issuing
    `DELETE ... LIMIT` — which Postgres does not support and SQLite only supports
    when compiled for it. The tuple form also covers the composite-key tables.
    """
    removed = 0
    for _ in range(MAX_BATCHES):
        with engine.begin() as conn:
            keys = conn.execute(
                select(*pk_columns).where(predicate).limit(BATCH)
            ).all()
            if not keys:
                return removed
            if len(pk_columns) == 1:
                column = pk_columns[0]
                result = conn.execute(
                    delete(table).where(column.in_([k[0] for k in keys]))
                )
            else:
                # Composite key: match each row explicitly.
                from sqlalchemy import and_, or_

                result = conn.execute(
                    delete(table).where(
                        or_(*[
                            and_(*[col == value for col, value in zip(pk_columns, key)])
                            for key in keys
                        ])
                    )
                )
            removed += result.rowcount or 0
        if len(keys) < BATCH:
            return removed
    return removed


def reap(engine: Engine) -> ReapReport:
    """Run every retention policy once. Idempotent."""
    now = utcnow()
    report = ReapReport()

    # Sync records: aged out. The biggest table, and the one with a privacy
    # dimension — it enumerates what one person's agent was shown.
    cutoff = now - timedelta(days=snapshot_retention_days())
    report.add(
        "context_snapshots",
        _delete_batched(
            engine,
            context_snapshots,
            context_snapshots.c.created_at < cutoff,
            [context_snapshots.c.id],
        ),
    )

    # Short-lived OAuth machinery: worthless the moment it expires.
    report.add(
        "auth_transactions",
        _delete_batched(
            engine,
            auth_transactions,
            auth_transactions.c.expires_at < now,
            [auth_transactions.c.txn_id],
        ),
    )
    report.add(
        "authorization_codes",
        _delete_batched(
            engine,
            authorization_codes,
            authorization_codes.c.expires_at < now,
            [authorization_codes.c.code_hash],
        ),
    )

    # Expired tokens cannot authenticate anything. Revoked ones linger briefly so
    # "when did this connection lose access" stays answerable.
    report.add(
        "oauth_tokens",
        _delete_batched(
            engine,
            oauth_tokens,
            oauth_tokens.c.expires_at < now,
            [oauth_tokens.c.id],
        ),
    )
    revoked_cutoff = now - timedelta(days=revoked_token_retention_days())
    report.add(
        "oauth_tokens",
        _delete_batched(
            engine,
            oauth_tokens,
            oauth_tokens.c.revoked_at.isnot(None)
            & (oauth_tokens.c.revoked_at < revoked_cutoff),
            [oauth_tokens.c.id],
        ),
    )

    report.add(
        "login_sessions",
        _delete_batched(
            engine,
            login_sessions,
            login_sessions.c.expires_at < now,
            [login_sessions.c.sid_hash],
        ),
    )
    report.add(
        "email_tokens",
        _delete_batched(
            engine,
            email_tokens,
            email_tokens.c.expires_at < now,
            [email_tokens.c.id],
        ),
    )

    # Abandoned client registrations. /register is reachable without credentials,
    # and rate limiting caps how *fast* rows arrive without bounding how many
    # accumulate — so an unmetered table becomes a slowly-metered one. A real
    # registration is followed by consent within seconds; one with no connection
    # after the grace period was abandoned (or was a probe) and authenticates
    # nothing. Clients that ever produced a connection are kept, including
    # revoked ones, because the audit trail refers to them.
    abandoned_cutoff = now - timedelta(days=abandoned_client_grace_days())
    used_clients = select(agent_connections.c.oauth_client_id).where(
        agent_connections.c.oauth_client_id.isnot(None)
    )
    report.add(
        "oauth_clients",
        _delete_batched(
            engine,
            oauth_clients,
            (oauth_clients.c.created_at < abandoned_cutoff)
            & oauth_clients.c.client_id.notin_(used_clients),
            [oauth_clients.c.client_id],
        ),
    )

    # Rate-limit counters. The purge has existed since V2 and was never called
    # from anywhere, so every login attempt ever made is still on disk.
    before = _count_rate_events(engine)
    RateLimiter(engine).purge_older_than(timedelta(days=1))
    report.add("rate_events", max(0, before - _count_rate_events(engine)))

    # audit_events is deliberately absent. It is small, append-only, and it is
    # the record you need when answering a question about who did what.
    return report


def preview(engine: Engine) -> ReapReport:
    """Count what `reap` would delete, without deleting it.

    Worth having before the first run against a production database that has been
    accumulating for months: it turns "this will delete some rows" into a number
    someone can sanity-check.
    """
    from sqlalchemy import func

    from .db import rate_events

    now = utcnow()
    report = ReapReport()

    checks = [
        (
            "context_snapshots",
            context_snapshots,
            context_snapshots.c.created_at
            < now - timedelta(days=snapshot_retention_days()),
        ),
        ("auth_transactions", auth_transactions, auth_transactions.c.expires_at < now),
        (
            "authorization_codes",
            authorization_codes,
            authorization_codes.c.expires_at < now,
        ),
        ("oauth_tokens", oauth_tokens, oauth_tokens.c.expires_at < now),
        ("login_sessions", login_sessions, login_sessions.c.expires_at < now),
        ("email_tokens", email_tokens, email_tokens.c.expires_at < now),
        (
            "oauth_clients",
            oauth_clients,
            (oauth_clients.c.created_at
             < now - timedelta(days=abandoned_client_grace_days()))
            & oauth_clients.c.client_id.notin_(
                select(agent_connections.c.oauth_client_id).where(
                    agent_connections.c.oauth_client_id.isnot(None)
                )
            ),
        ),
        (
            "rate_events",
            rate_events,
            rate_events.c.window_start < now - timedelta(days=1),
        ),
    ]
    with engine.begin() as conn:
        for name, table, predicate in checks:
            count = conn.execute(
                select(func.count()).select_from(table).where(predicate)
            ).scalar_one()
            report.add(name, int(count))
    return report


def _count_rate_events(engine: Engine) -> int:
    from sqlalchemy import func

    from .db import rate_events

    with engine.begin() as conn:
        return int(
            conn.execute(select(func.count()).select_from(rate_events)).scalar_one()
        )
