"""Console pages: context list, create, browse, share, retract."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def console(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    monkeypatch.setenv("SAC_EMAIL_PROVIDER", "console")
    runtime.set_store(seed.store)
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")

    app = FastAPI()
    from app.auth.web import router as auth_router
    from app.control import router as console_router

    app.include_router(auth_router)
    app.include_router(console_router)
    client = TestClient(app, follow_redirects=False)
    r = client.post("/auth/login", data={
        "email": "alice@example.com", "password": "correct-horse-battery"
    })
    assert r.status_code == 303
    yield client, seed


def test_home_lists_contexts_with_access(console):
    c, _ = console
    r = c.get("/console")
    assert r.status_code == 200
    assert "Shared Desktop App" in r.text
    assert "owner" in r.text


def test_home_shows_connected_clients(console):
    c, seed = console
    seed.store.projects.set_binding(seed.alice_user_id, seed.project_id, seed.alice_conn)
    r = c.get("/console")
    assert "Alice / ChatGPT" in r.text
    assert "Shared Desktop App" in r.text


def test_create_context_from_the_web(console):
    c, seed = console
    r = c.post("/console/contexts", data={"name": "Launch Plan", "description": "Q4"})
    assert r.status_code == 303
    assert r.headers["location"].startswith("/console/c/")
    names = {x["name"] for x in seed.store.projects.list_user_contexts(seed.alice_user_id)}
    assert "Launch Plan" in names


def test_unverified_user_cannot_create_from_web(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    runtime.set_store(seed.store)
    uid = seed.store.projects.create_user("unverified@example.com", "U")
    seed.store.auth.set_password(uid, "correct-horse-battery")

    app = FastAPI()
    from app.auth.web import router as auth_router
    from app.control import router as console_router

    app.include_router(auth_router)
    app.include_router(console_router)
    c = TestClient(app, follow_redirects=False)
    c.post("/auth/login", data={
        "email": "unverified@example.com", "password": "correct-horse-battery"})
    r = c.post("/console/contexts", data={"name": "Nope"})
    assert r.status_code == 400
    assert "verify your email" in r.text


def test_context_page_shows_memory_members_and_audit(console):
    c, seed = console
    seed.store.memories.remember(seed.alice, scope="shared", kind="decision",
                                 summary="Use Supabase Auth.")
    r = c.get(f"/console/c/{seed.project_id}")
    assert r.status_code == 200
    assert "Use Supabase Auth." in r.text
    assert "bob@example.com" in r.text
    assert "Recent activity" in r.text


def test_share_form_visible_to_owner_only(console, seed):
    c, _ = console
    assert "Share this context" in c.get(f"/console/c/{seed.project_id}").text

    # bob is a member (edit) — no share form
    seed.store.auth.set_password(seed.bob_user_id, "correct-horse-battery")
    c.cookies.clear()
    c.post("/auth/login", data={"email": "bob@example.com", "password": "correct-horse-battery"})
    assert "Share this context" not in c.get(f"/console/c/{seed.project_id}").text


def test_share_from_the_web_grants_access(console):
    c, seed = console
    r = c.post(f"/console/c/{seed.project_id}/share",
               data={"email": "carol@example.com", "access": "view"})
    assert r.status_code == 303
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    assert seed.store.projects.get_role(seed.project_id, carol["id"]) == "viewer"


def test_share_with_unknown_email_creates_pending_invite(console):
    c, seed = console
    c.post(f"/console/c/{seed.project_id}/share",
           data={"email": "newcomer@example.com", "access": "edit"})
    r = c.get(f"/console/c/{seed.project_id}")
    assert "newcomer@example.com" in r.text
    assert "invited" in r.text


def test_revoke_member_from_the_web(console):
    c, seed = console
    r = c.post(f"/console/c/{seed.project_id}/revoke", data={"user_id": seed.bob_user_id})
    assert r.status_code == 303
    assert seed.store.projects.get_role(seed.project_id, seed.bob_user_id) is None


def test_cannot_revoke_last_owner_from_web(console):
    c, seed = console
    r = c.post(f"/console/c/{seed.project_id}/revoke", data={"user_id": seed.alice_user_id})
    assert r.status_code == 400
    assert "at least one owner" in r.text


def test_retract_removes_from_active_context(console):
    c, seed = console
    out = seed.store.memories.remember(seed.alice, scope="shared", kind="decision",
                                       summary="Temporary decision.")
    mid = out["memory"].id
    r = c.post(f"/console/c/{seed.project_id}/memories/{mid}/retract")
    assert r.status_code == 303
    assert seed.store.memories.get_memory(
        seed.project_id, mid, seed.alice_user_id).status == "retracted"


def test_non_member_gets_403(console, seed):
    c, _ = console
    r = c.get(f"/console/c/{seed.other_project_id}")
    assert r.status_code == 403


def test_unauthenticated_redirects_to_login_with_next(seed, monkeypatch):
    import app.runtime as runtime

    runtime.set_store(seed.store)
    app = FastAPI()
    from app.control import router as console_router

    app.include_router(console_router)
    c = TestClient(app, follow_redirects=False)
    r = c.get("/console")
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login?next=/console"
