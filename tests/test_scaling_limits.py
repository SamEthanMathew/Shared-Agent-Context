"""Limits and query scoping that only matter once there are many tenants.

Every case here passes trivially at two users, which is exactly why they were
missing. Three separate problems:

**A query whose cost tracks the whole database.** `list_user_contexts` counted
memberships across every project that exists, not the caller's, on the most-hit
endpoint in the product.

**A quota that was never wired up.** `MAX_MEMORIES_PER_CONTEXT` was imported and
never used, so one context could grow until it filled the disk.

**Unmetered anonymous endpoints.** `/register` and `/token` are reachable without
credentials and each registration writes a permanent row; the per-token tool-call
ceiling was likewise defined and never enforced.
"""
from __future__ import annotations

import pytest

from app.errors import ConflictError


# --- the aggregate must not scan the world ----------------------------------


def test_member_count_ignores_other_tenants_contexts(seed):
    """Carol's separate project must not perturb Alice's counts.

    The regression this guards: the count was a whole-table GROUP BY, so it
    happened to be correct while being O(all memberships in the database).
    """
    ps = seed.store.projects
    # Build a busy neighbouring tenant that Alice has nothing to do with.
    noisy = ps.create_project("Carol Big Project", owner_user_id=seed.carol.user_id)
    for n in range(6):
        other = ps.create_user(f"stranger{n}@example.com", f"S{n}")
        ps.add_membership(noisy.id, other, role="member")

    contexts = ps.list_user_contexts(seed.alice_user_id)
    assert [c["name"] for c in contexts] == ["Shared Desktop App"]
    assert contexts[0]["member_count"] == 2  # alice + bob, not 8


def test_member_count_is_still_correct_for_shared_contexts(seed):
    ps = seed.store.projects
    dave = ps.create_user("dave@example.com", "Dave")
    ps.add_membership(seed.project_id, dave, role="viewer")
    contexts = ps.list_user_contexts(seed.alice_user_id)
    assert contexts[0]["member_count"] == 3


def test_listing_contexts_does_not_query_unrelated_memberships(seed):
    """Pin the cost, not just the answer.

    Counting the rows the statement touches is the only way to keep this from
    silently regressing to a whole-table aggregate again — the return value is
    identical either way.
    """
    from sqlalchemy import event

    ps = seed.store.projects
    noisy = ps.create_project("Carol Big Project", owner_user_id=seed.carol.user_id)
    for n in range(5):
        other = ps.create_user(f"stranger{n}@example.com", f"S{n}")
        ps.add_membership(noisy.id, other, role="member")

    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(seed.store.engine, "before_cursor_execute", record)
    try:
        ps.list_user_contexts(seed.alice_user_id)
    finally:
        event.remove(seed.store.engine, "before_cursor_execute", record)

    aggregates = [s for s in seen if "count" in s.lower()]
    assert aggregates, "expected a count query"
    for statement in aggregates:
        # An unbounded GROUP BY has no project filter. The scoped version must.
        assert "project_id IN" in statement or "project_id =" in statement, (
            f"membership count is not scoped to the caller:\n{statement}"
        )


# --- the per-context memory quota -------------------------------------------


def test_a_context_cannot_grow_past_its_memory_quota(seed, monkeypatch):
    import app.stores.memories as memories_module

    monkeypatch.setattr(memories_module, "MAX_MEMORIES_PER_CONTEXT", 3)
    for n in range(3):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary=f"note {n}"
        )
    with pytest.raises(ConflictError) as exc:
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary="one too many"
        )
    assert "limit reached" in str(exc.value)


def test_the_quota_counts_private_memory_too(seed, monkeypatch):
    """Otherwise private writes are a way around the cap."""
    import app.stores.memories as memories_module

    monkeypatch.setattr(memories_module, "MAX_MEMORIES_PER_CONTEXT", 2)
    seed.store.memories.remember(
        seed.alice, scope="private", kind="note", summary="mine"
    )
    seed.store.memories.remember(
        seed.bob, scope="private", kind="note", summary="bob's"
    )
    with pytest.raises(ConflictError):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary="over the line"
        )


def test_retracting_frees_quota(seed, monkeypatch):
    """The cap is on live memory, so withdrawing something makes room."""
    import app.stores.memories as memories_module

    monkeypatch.setattr(memories_module, "MAX_MEMORIES_PER_CONTEXT", 2)
    first = seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="first"
    )
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="second"
    )
    with pytest.raises(ConflictError):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary="third"
        )
    seed.store.memories.retract(seed.alice, first["memory"].id)
    assert seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="third, now allowed"
    )


def test_the_quota_is_per_context_not_global(seed, monkeypatch):
    """One busy context must not stop a different one from being written to."""
    import app.stores.memories as memories_module

    monkeypatch.setattr(memories_module, "MAX_MEMORIES_PER_CONTEXT", 1)
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="fills context P"
    )
    assert seed.store.memories.remember(
        seed.carol, scope="shared", kind="note", summary="context Q is unaffected"
    )


# --- liveness must not depend on table size ---------------------------------


def test_health_does_not_count_users(wired):
    """Render polls this constantly; it must not scan a growing table."""
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    body = c.get("/health").json()
    assert body["ok"] is True
    assert "users" not in body, "liveness should not report table statistics"


def test_health_still_fails_if_the_database_is_unreachable(wired, monkeypatch):
    """Dropping the count must not turn liveness into a check of nothing."""
    from fastapi.testclient import TestClient

    from app.main import app

    def _broken():
        raise RuntimeError("database is down")

    monkeypatch.setattr(wired.store.engine, "connect", _broken)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/health").status_code >= 500


# --- the anonymous OAuth endpoints are metered ------------------------------


@pytest.fixture
def limited(wired, monkeypatch):
    """The real app with tiny rate-limit budgets, so tests stay fast."""
    from fastapi.testclient import TestClient

    import app.limits as limits

    monkeypatch.setitem(limits.LIMITS, "register", (3, 3600))
    monkeypatch.setitem(limits.LIMITS, "token", (3, 300))
    monkeypatch.setitem(limits.LIMITS, "tool_call", (3, 60))

    from app.main import app

    return TestClient(app, follow_redirects=False), wired


def test_dynamic_client_registration_is_rate_limited(limited):
    """Each registration writes a permanent row, so anonymous callers get a cap."""
    c, _ = limited
    body = {
        "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
    }
    codes = [c.post("/register", json=body).status_code for _ in range(5)]
    assert 429 in codes, f"registration was never throttled: {codes}"
    # And the refusal is actionable rather than a bare error.
    throttled = c.post("/register", json=body)
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers


def test_the_token_endpoint_is_rate_limited(limited):
    c, _ = limited
    codes = [
        c.post("/token", data={"grant_type": "authorization_code", "code": "nope"}).status_code
        for _ in range(5)
    ]
    assert 429 in codes, f"token endpoint was never throttled: {codes}"


def test_tool_calls_are_metered_per_connection_not_per_address(limited):
    """One runaway agent must not throttle a colleague on the same network."""
    c, _ = limited
    busy = {"Authorization": "Bearer token-belonging-to-the-busy-client"}
    quiet = {"Authorization": "Bearer token-belonging-to-someone-else"}

    codes = [c.get("/v1/contexts", headers=busy).status_code for _ in range(5)]
    assert 429 in codes, f"tool calls were never throttled: {codes}"

    # The other token shares the IP but not the bucket. It is unauthenticated
    # here, so 401 is the expected answer — the point is that it is not 429.
    assert c.get("/v1/contexts", headers=quiet).status_code != 429


def test_rate_limiting_runs_before_authentication(limited):
    """A throttled caller should not cost us a token verification."""
    c, _ = limited
    headers = {"Authorization": "Bearer some-token"}
    for _ in range(4):
        c.get("/v1/contexts", headers=headers)
    r = c.get("/v1/contexts", headers=headers)
    assert r.status_code == 429  # not 401


def test_ordinary_browsing_is_not_throttled(limited):
    """The limits must not touch the pages people actually use."""
    c, _ = limited
    for _ in range(8):
        assert c.get("/health").status_code == 200
        assert c.get("/auth/login").status_code == 200
