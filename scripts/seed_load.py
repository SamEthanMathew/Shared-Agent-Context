"""Generate a realistically-shaped database, then time the hot queries.

The point is not to prove the code is fast. It is to check whether the diagnosis
behind the Phase 1 and 2 changes was actually right — a claim like "this query's
cost tracks total tenants" is either visible in a timing at scale or it was
wrong, and either answer is worth having.

    python scripts/seed_load.py --users 500 --contexts 800 --memories 40000
    python scripts/seed_load.py --measure-only        # re-time an existing DB

Writes with bulk inserts rather than the store API: this needs a shape to
measure, not a faithful history, and going through the store would take hours.
Point DATABASE_URL at a scratch database — never at production.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sqlalchemy import func, select  # noqa: E402

from app.db import (  # noqa: E402
    context_snapshots,
    memberships,
    memories,
    metadata,
    projects,
    users,
)
from app.stores import SACStore  # noqa: E402

# Deterministic, so two runs are comparable.
RNG = random.Random(20260812)

WORDS = (
    "deploy kubernetes postgres billing invoice retry latency schema migration "
    "auth session token cache index queue worker webhook payment refund ledger "
    "onboarding retention pricing checkout inventory shipping refund dispute"
).split()
KINDS = ("decision", "requirement", "constraint", "finding", "result", "note")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seed(store: SACStore, n_users: int, n_contexts: int, n_memories: int,
         n_snapshots: int) -> dict[str, str]:
    metadata.create_all(store.engine)
    now = _now()

    print(f"[seed] {n_users} users…")
    user_ids = [str(uuid.uuid4()) for _ in range(n_users)]
    with store.engine.begin() as conn:
        conn.execute(
            users.insert(),
            [
                {
                    "id": uid, "email": f"user{i}@example.com",
                    "display_name": f"User {i}", "password_hash": None,
                    "is_admin": 0, "created_at": now,
                    "email_verified_at": now, "failed_login_count": 0,
                }
                for i, uid in enumerate(user_ids)
            ],
        )

    print(f"[seed] {n_contexts} contexts…")
    project_ids = [str(uuid.uuid4()) for _ in range(n_contexts)]
    with store.engine.begin() as conn:
        conn.execute(
            projects.insert(),
            [
                {
                    "id": pid, "name": f"Context {i}", "slug": f"context-{i}",
                    "description": "", "owner_user_id": user_ids[i % n_users],
                    "context_revision": 0, "settings": {},
                    "created_at": now, "updated_at": now,
                    "link_access": "none", "org_access": "none",
                }
                for i, pid in enumerate(project_ids)
            ],
        )

        # Memberships: an owner plus a handful of others. This is the table whose
        # size used to be scanned on every /v1/me.
        rows = []
        for i, pid in enumerate(project_ids):
            rows.append({
                "project_id": pid, "user_id": user_ids[i % n_users],
                "role": "owner", "source": "direct", "created_at": now,
            })
            for _ in range(RNG.randint(1, 5)):
                uid = user_ids[RNG.randrange(n_users)]
                if uid != user_ids[i % n_users]:
                    rows.append({
                        "project_id": pid, "user_id": uid,
                        "role": "member", "source": "direct", "created_at": now,
                    })
        # Deduplicate on the composite key.
        seen, unique = set(), []
        for r in rows:
            key = (r["project_id"], r["user_id"])
            if key not in seen:
                seen.add(key)
                unique.append(r)
        print(f"[seed] {len(unique)} memberships…")
        conn.execute(memberships.insert(), unique)

    # Concentrate memory in the first few contexts, the way real use does: a
    # couple of busy projects and a long tail of quiet ones. The busiest is what
    # the compile query has to cope with.
    print(f"[seed] {n_memories} memories…")
    hot = project_ids[:5]
    batch, written = [], 0
    for i in range(n_memories):
        pid = hot[i % len(hot)] if i % 3 else project_ids[RNG.randrange(n_contexts)]
        summary = " ".join(RNG.sample(WORDS, RNG.randint(6, 12)))
        batch.append({
            "id": str(uuid.uuid4()), "project_id": pid, "revision": i + 1,
            "scope": "shared" if i % 4 else "private",
            "owner_user_id": None if i % 4 else user_ids[RNG.randrange(n_users)],
            "kind": KINDS[i % len(KINDS)], "summary": summary,
            # Deliberately large: this is the field ranking used to tokenise.
            "details": " ".join(RNG.choices(WORDS, k=300)),
            "tags": ",".join(RNG.sample(WORDS, 3)), "status": "active",
            "importance": 0.6, "confidence": 0.7, "authority": "member",
            "sensitivity": "internal", "version": 1, "superseded_by_id": None,
            "created_by_user_id": user_ids[RNG.randrange(n_users)],
            "created_by_agent_id": None, "origin_session_id": None,
            "source_event_id": None, "valid_from": None, "valid_until": None,
            "created_at": now, "updated_at": now,
        })
        if len(batch) >= 2000:
            with store.engine.begin() as conn:
                conn.execute(memories.insert(), batch)
            written += len(batch)
            batch = []
            print(f"[seed]   {written}/{n_memories}", end="\r")
    if batch:
        with store.engine.begin() as conn:
            conn.execute(memories.insert(), batch)
    print(f"[seed]   {n_memories}/{n_memories} memories   ")

    print(f"[seed] {n_snapshots} sync records…")
    batch = []
    for i in range(n_snapshots):
        pid = hot[i % len(hot)]
        batch.append({
            "id": str(uuid.uuid4()), "project_id": pid, "session_id": None,
            "user_id": user_ids[RNG.randrange(n_users)],
            "agent_connection_id": None, "project_revision": i + 1,
            "task": " ".join(RNG.sample(WORDS, 5)),
            "budget_tokens": 3000, "token_estimate": 2400,
            "included": [], "excluded": [], "compiler_policy": "lexical_v1",
            "created_at": now - timedelta(days=RNG.randint(0, 200)),
        })
        if len(batch) >= 2000:
            with store.engine.begin() as conn:
                conn.execute(context_snapshots.insert(), batch)
            batch = []
    if batch:
        with store.engine.begin() as conn:
            conn.execute(context_snapshots.insert(), batch)

    return {"user_id": user_ids[0], "project_id": hot[0]}


def _time(label: str, fn, repeat: int = 5) -> float:
    """Best-of-N wall clock, in milliseconds. Best, not mean: we are measuring
    the query, and the slowest runs are measuring the machine's other work."""
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - start) * 1000)
    print(f"  {label:<44} {best:8.2f} ms")
    return best


def measure(store: SACStore) -> None:
    with store.engine.begin() as conn:
        counts = {
            "users": conn.execute(select(func.count()).select_from(users)).scalar_one(),
            "contexts": conn.execute(
                select(func.count()).select_from(projects)
            ).scalar_one(),
            "memberships": conn.execute(
                select(func.count()).select_from(memberships)
            ).scalar_one(),
            "memories": conn.execute(
                select(func.count()).select_from(memories)
            ).scalar_one(),
            "snapshots": conn.execute(
                select(func.count()).select_from(context_snapshots)
            ).scalar_one(),
        }
    print("\n[measure] shape:", ", ".join(f"{k}={v}" for k, v in counts.items()))

    with store.engine.begin() as conn:
        user_id = conn.execute(select(users.c.id).limit(1)).scalar_one()
        # The busiest context: whichever holds the most live memory.
        project_id = conn.execute(
            select(memories.c.project_id)
            .group_by(memories.c.project_id)
            .order_by(func.count().desc())
            .limit(1)
        ).scalar_one()
        busiest = conn.execute(
            select(func.count())
            .select_from(memories)
            .where(memories.c.project_id == project_id)
        ).scalar_one()
        owner_id = conn.execute(
            select(memberships.c.user_id).where(
                memberships.c.project_id == project_id
            ).limit(1)
        ).scalar_one()
    print(f"[measure] busiest context holds {busiest} memories\n")

    print("[measure] hot read paths:")
    _time(
        "list_user_contexts (powers /v1/me)",
        lambda: store.projects.list_user_contexts(user_id),
    )
    _time(
        "resolve_identity (every tool call)",
        lambda: store.projects.resolve_context_ref(owner_id, project_id),
    )
    _time(
        "compile_candidates (busiest context)",
        lambda: store.memories.compile_candidates(project_id, owner_id),
    )

    candidates = store.memories.compile_candidates(project_id, owner_id)
    _time(
        f"rank ({len(candidates)} candidates)",
        lambda: store.memories.rank(candidates, "deploy kubernetes latency"),
    )
    _time(
        "list_memories (100)",
        lambda: store.memories.list_memories(project_id, owner_id, limit=100),
    )
    _time(
        "snapshots for one user",
        lambda: store.snapshots.list_for_user(project_id, owner_id),
    )
    _time(
        "count_memories",
        lambda: store.memories.count_memories(project_id, owner_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=500)
    parser.add_argument("--contexts", type=int, default=800)
    parser.add_argument("--memories", type=int, default=40_000)
    parser.add_argument("--snapshots", type=int, default=10_000)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()

    url = os.getenv("DATABASE_URL", "")
    if "onrender.com" in url or "render" in url.lower():
        print("[abort] DATABASE_URL looks like production. Point it elsewhere.")
        return 2

    store = SACStore()
    if not args.measure_only:
        started = time.perf_counter()
        seed(store, args.users, args.contexts, args.memories, args.snapshots)
        print(f"[seed] done in {time.perf_counter() - started:.1f}s")
    measure(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
