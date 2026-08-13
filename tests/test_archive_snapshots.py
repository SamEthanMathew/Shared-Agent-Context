"""Context archiving and agent-transparency (snapshot) records.

Both completed half-built features: `projects.archived_at` was filtered on but
never set, and context_snapshots were recorded but only retrievable if you
already knew the id.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import resolve_context
from app.context import compile_context
from app.errors import ForbiddenError, NeedsContextSelection
from app.identity import Principal
from app.models import READ_SCOPE, WRITE_SCOPE


def _principal(seed, which="alice"):
    if which == "alice":
        return Principal(seed.alice_user_id, seed.alice_conn, (READ_SCOPE, WRITE_SCOPE))
    return Principal(seed.bob_user_id, seed.bob_conn, (READ_SCOPE, WRITE_SCOPE))


# --- archiving --------------------------------------------------------------


def test_archived_context_leaves_the_listing(seed):
    ps = seed.store.projects
    assert [c["name"] for c in ps.list_user_contexts(seed.alice_user_id)] == [
        "Shared Desktop App"
    ]
    ps.archive_project(seed.project_id)
    assert ps.list_user_contexts(seed.alice_user_id) == []
    assert [a["name"] for a in ps.list_archived_contexts(seed.alice_user_id)] == [
        "Shared Desktop App"
    ]


def test_archived_context_cannot_be_resolved_by_name_or_id(seed):
    ps = seed.store.projects
    ps.archive_project(seed.project_id)
    with pytest.raises(ForbiddenError):
        ps.resolve_context_ref(seed.alice_user_id, "Shared Desktop App")
    with pytest.raises(ForbiddenError):
        ps.resolve_context_ref(seed.alice_user_id, seed.project_id)


def test_archived_context_is_refused_by_resolve_identity(seed):
    """Closes the /v1 hole: a raw id must not reach an archived context."""
    seed.store.projects.archive_project(seed.project_id)
    with pytest.raises(ForbiddenError) as exc:
        seed.store.resolve_identity(_principal(seed), seed.project_id)
    assert "archived" in str(exc.value)
    # the restore path may still resolve it
    ident = seed.store.resolve_identity(
        _principal(seed), seed.project_id, allow_archived=True
    )
    assert ident.role == "owner"


def test_archiving_clears_bindings(seed):
    ps = seed.store.projects
    ps.set_binding(seed.alice_user_id, seed.project_id, seed.alice_conn)
    ps.archive_project(seed.project_id)
    assert ps.get_binding(seed.alice_user_id, seed.alice_conn) is None
    # and the caller is asked to choose rather than silently landing somewhere
    with pytest.raises(NeedsContextSelection):
        resolve_context(seed.store, _principal(seed))


def test_unarchive_restores_access(seed):
    ps = seed.store.projects
    ps.archive_project(seed.project_id)
    ps.unarchive_project(seed.project_id)
    assert [c["name"] for c in ps.list_user_contexts(seed.alice_user_id)] == [
        "Shared Desktop App"
    ]
    assert ps.resolve_context_ref(seed.alice_user_id, "Shared Desktop App") == seed.project_id


def test_archiving_retains_memory(seed):
    """Archiving is a projection, not a deletion."""
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Still here."
    )
    ps = seed.store.projects
    ps.archive_project(seed.project_id)
    ps.unarchive_project(seed.project_id)
    m = seed.store.memories.get_memory(
        seed.project_id, out["memory"].id, seed.alice_user_id
    )
    assert m is not None and m.summary == "Still here."


def test_archived_name_frees_the_slug_conflict_only_by_suffix(seed):
    """A new context with the same name still gets a distinct slug."""
    ps = seed.store.projects
    ps.archive_project(seed.project_id)
    fresh = ps.create_project("Shared Desktop App", owner_user_id=seed.alice_user_id)
    assert fresh.slug == "shared-desktop-app-2"


# --- snapshot transparency --------------------------------------------------


def _sync(seed, identity, user_id, ref, task):
    session = seed.store.sessions.get_or_create(seed.project_id, user_id, ref)
    return compile_context(seed.store, identity, session, task)


def test_snapshots_are_listed_for_their_owner(seed):
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Recorded decision."
    )
    _sync(seed, seed.alice, seed.alice_user_id, "chat-1", "first question")
    _sync(seed, seed.alice, seed.alice_user_id, "chat-1", "second question")

    snaps = seed.store.snapshots.list_for_user(seed.project_id, seed.alice_user_id)
    assert len(snaps) == 2
    tasks = {s["task"] for s in snaps}
    assert tasks == {"first question", "second question"}
    assert all(s["token_estimate"] > 0 for s in snaps)
    assert all(s["included_count"] >= 1 for s in snaps)


def test_snapshots_are_private_to_the_user(seed):
    """A snapshot enumerates what one person's agent saw — including their
    private memories — so it is not visible to other members."""
    _sync(seed, seed.alice, seed.alice_user_id, "chat-1", "alice question")
    assert seed.store.snapshots.list_for_user(seed.project_id, seed.bob_user_id) == []
    assert len(seed.store.snapshots.list_for_user(seed.project_id, seed.alice_user_id)) == 1


def test_snapshot_reports_withheld_private_count(seed):
    """The manifest says how much was kept back without naming it."""
    seed.store.memories.remember(
        seed.alice, scope="private", kind="note", summary="Alice private."
    )
    _sync(seed, seed.bob, seed.bob_user_id, "chat-b", "what do we know")
    snaps = seed.store.snapshots.list_for_user(seed.project_id, seed.bob_user_id)
    assert snaps[0]["withheld_private"] == 1


# --- console surfaces -------------------------------------------------------


@pytest.fixture
def console(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    runtime.set_store(seed.store)
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")
    app = FastAPI()
    from app.auth.web import router as auth_router
    from app.control import router as console_router

    app.include_router(auth_router)
    app.include_router(console_router)
    c = TestClient(app, follow_redirects=False)
    c.post("/auth/login", data={"email": "alice@example.com",
                                "password": "correct-horse-battery"})
    return c, seed


def test_console_archive_then_restore(console):
    c, seed = console
    r = c.post(f"/console/c/{seed.project_id}/archive")
    assert r.status_code == 303 and r.headers["location"] == "/console"
    home = c.get("/console").text
    assert "Archived" in home and "Restore" in home

    r = c.post(f"/console/c/{seed.project_id}/unarchive")
    assert r.status_code == 303
    assert seed.store.projects.list_user_contexts(seed.alice_user_id)


def test_non_owner_cannot_archive(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    runtime.set_store(seed.store)
    seed.store.auth.set_password(seed.bob_user_id, "correct-horse-battery")
    app = FastAPI()
    from app.auth.web import router as auth_router
    from app.control import router as console_router

    app.include_router(auth_router)
    app.include_router(console_router)
    c = TestClient(app, follow_redirects=False)
    c.post("/auth/login", data={"email": "bob@example.com",
                                "password": "correct-horse-battery"})
    r = c.post(f"/console/c/{seed.project_id}/archive")
    assert r.status_code == 403
    assert seed.store.projects.get_project(seed.project_id).archived_at is None


def test_console_snapshot_pages(console):
    c, seed = console
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Visible decision."
    )
    _sync(seed, seed.alice, seed.alice_user_id, "chat-1", "what did we decide")

    r = c.get(f"/console/c/{seed.project_id}/snapshots")
    assert r.status_code == 200
    assert "what did we decide" in r.text

    snap_id = seed.store.snapshots.list_for_user(
        seed.project_id, seed.alice_user_id
    )[0]["id"]
    r = c.get(f"/console/c/{seed.project_id}/snapshots/{snap_id}")
    assert r.status_code == 200
    assert "Visible decision." in r.text
    assert "Included" in r.text and "Withheld" in r.text


def test_cannot_view_another_users_snapshot(console):
    c, seed = console
    # a snapshot belonging to bob
    _sync(seed, seed.bob, seed.bob_user_id, "chat-b", "bob question")
    snap_id = seed.store.snapshots.list_for_user(
        seed.project_id, seed.bob_user_id
    )[0]["id"]
    r = c.get(f"/console/c/{seed.project_id}/snapshots/{snap_id}")
    assert r.status_code == 403
