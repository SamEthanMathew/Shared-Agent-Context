"""Identity must not cross between concurrent callers.

This is the one failure that would be catastrophic and silent: under load, two
people's requests served at the same time returning each other's contexts. It
cannot happen at two users taking turns, which is why it deserves an explicit
test rather than trust.

The mechanism being relied on: MCP tools and REST handlers here are synchronous,
so they run in anyio's worker threads, and the SDK carries the verified token in
a contextvar. anyio copies the calling context into the worker thread, so each
call sees its own. That is a property of two libraries composing correctly — the
kind of thing that holds until a dependency changes it, and then fails quietly.

Also covers the connection pool under saturation, since capping the thread pool
to the pool size (Phase 2) is only correct if a saturated pool still serves every
request rather than dropping or crossing any.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.browser import CSRF_COOKIE, CSRF_HEADER


@pytest.fixture
def app_with_users(wired, monkeypatch):
    """Three accounts, each owning a differently-named context."""
    from app.main import app

    seed = wired
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")

    people = {}
    for name in ("ann", "ben", "cat"):
        uid = seed.store.projects.create_user(f"{name}@concurrent.test", name)
        seed.store.auth.mark_email_verified(uid)
        seed.store.auth.set_password(uid, "correct-horse-battery")
        project = seed.store.projects.create_project(
            f"{name.title()} Only Context", owner_user_id=uid
        )
        seed.store.memories.remember(
            seed.store.resolve_identity(_principal(uid), project.id),
            scope="shared", kind="note", summary=f"{name}'s private business",
        )
        people[name] = {"user_id": uid, "project_id": project.id}
    return app, seed, people


def _principal(user_id: str):
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    return Principal(user_id, None, (READ_SCOPE, WRITE_SCOPE))


def _signed_in_client(app, email: str) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    r = client.post(
        "/auth/login", data={"email": email, "password": "correct-horse-battery"}
    )
    assert r.status_code == 303, r.text
    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
    return client


# --- identity isolation -----------------------------------------------------


def test_concurrent_callers_never_see_each_others_contexts(app_with_users):
    """The catastrophic-and-silent failure, checked directly."""
    app, _seed, people = app_with_users
    clients = {
        name: _signed_in_client(app, f"{name}@concurrent.test") for name in people
    }

    def fetch(name: str) -> tuple[str, list[str]]:
        body = clients[name].get("/v1/me").json()
        return name, [c["name"] for c in body["contexts"]]

    # Interleave many requests from all three accounts at once.
    order = [name for name in people for _ in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetch, order))

    assert len(results) == len(order)
    for name, contexts in results:
        assert contexts == [f"{name.title()} Only Context"], (
            f"{name} saw {contexts} — identity crossed between requests"
        )


def test_concurrent_memory_reads_stay_within_their_own_context(app_with_users):
    """The same property one layer deeper: at the memory, not the listing."""
    app, _seed, people = app_with_users
    clients = {
        name: _signed_in_client(app, f"{name}@concurrent.test") for name in people
    }

    def read(name: str) -> tuple[str, list[str]]:
        project_id = people[name]["project_id"]
        body = clients[name].get(f"/v1/projects/{project_id}/memories").json()
        return name, [m["summary"] for m in body["memories"]]

    order = [name for name in people for _ in range(10)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(read, order))

    for name, summaries in results:
        assert summaries == [f"{name}'s private business"], (
            f"{name} read {summaries}"
        )


def test_a_concurrent_cross_tenant_read_is_still_refused(app_with_users):
    """Load must not soften the boundary: Ann asking for Ben's context, repeatedly
    and simultaneously, gets 403 every time."""
    app, _seed, people = app_with_users
    ann = _signed_in_client(app, "ann@concurrent.test")
    bens_project = people["ben"]["project_id"]

    def attempt(_: int) -> int:
        return ann.get(f"/v1/projects/{bens_project}/memories").status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(attempt, range(30)))

    assert set(codes) == {403}, f"got {sorted(set(codes))}"


# --- the pool under saturation ----------------------------------------------


def test_every_request_is_served_when_the_pool_is_saturated(app_with_users):
    """Capping the thread pool to the connection pool (Phase 2) is only right if
    a saturated pool queues rather than fails."""
    app, _seed, people = app_with_users
    ann = _signed_in_client(app, "ann@concurrent.test")
    project_id = people["ann"]["project_id"]

    def hit(_: int) -> int:
        return ann.get(f"/v1/projects/{project_id}").status_code

    with ThreadPoolExecutor(max_workers=24) as pool:
        codes = list(pool.map(hit, range(120)))

    assert set(codes) == {200}, f"some requests were not served: {sorted(set(codes))}"


def test_concurrent_writes_all_get_distinct_revisions(app_with_users):
    """Revision allocation takes a row lock per context. Under concurrent writes
    every memory must still get its own revision — a duplicate would violate the
    uniqueness constraint and, worse, make the change feed skip an entry."""
    app, seed, people = app_with_users
    project_id = people["ann"]["project_id"]
    identity = seed.store.resolve_identity(
        _principal(people["ann"]["user_id"]), project_id
    )

    def write(n: int) -> int:
        out = seed.store.memories.remember(
            identity, scope="shared", kind="note", summary=f"concurrent {n}"
        )
        return out["memory"].revision

    with ThreadPoolExecutor(max_workers=8) as pool:
        revisions = list(pool.map(write, range(24)))

    assert len(set(revisions)) == len(revisions), (
        f"duplicate revisions allocated: {sorted(revisions)}"
    )
