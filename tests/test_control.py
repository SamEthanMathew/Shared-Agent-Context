"""Control-plane pages: login-gated project view, inspection, retract."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def console(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    runtime.set_store(seed.store)
    seed.store.auth.set_password(seed.alice_user_id, "pw")

    app = FastAPI()
    from app.auth.web import router as auth_router
    from app.control import router as console_router

    app.include_router(auth_router)
    app.include_router(console_router)
    client = TestClient(app, follow_redirects=False)
    # log in as alice (no txn → lands on console)
    r = client.post("/auth/login", data={"email": "alice@example.com", "password": "pw"})
    assert r.status_code == 303
    yield client, seed


def test_home_lists_projects(console):
    c, seed = console
    r = c.get("/console")
    assert r.status_code == 200
    assert "Shared Desktop App" in r.text


def test_project_page_shows_memory_and_members(console):
    c, seed = console
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Use Supabase Auth."
    )
    r = c.get(f"/console/projects/{seed.project_id}")
    assert r.status_code == 200
    assert "Use Supabase Auth." in r.text
    assert "alice@example.com" in r.text or "Alice" in r.text
    assert "bob@example.com" in r.text or "Bob" in r.text


def test_retract_removes_from_active(console):
    c, seed = console
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Temporary decision."
    )
    mid = out["memory"].id
    r = c.post(f"/console/projects/{seed.project_id}/memories/{mid}/retract")
    assert r.status_code == 303
    m = seed.store.memories.get_memory(seed.project_id, mid, seed.alice_user_id)
    assert m.status == "retracted"
    # no longer a compile candidate
    active = {x.id for x in seed.store.memories.compile_candidates(seed.project_id, seed.alice_user_id)}
    assert mid not in active


def test_non_member_project_page_403(console):
    c, seed = console
    # carol's project — alice is not a member
    r = c.get(f"/console/projects/{seed.other_project_id}")
    assert r.status_code == 403


def test_unauthenticated_redirects_to_login():
    from app.stores import SACStore
    import app.runtime as runtime

    store = SACStore("sqlite:///:memory:")
    store.init()
    runtime.set_store(store)
    app = FastAPI()
    from app.control import router as console_router

    app.include_router(console_router)
    c = TestClient(app, follow_redirects=False)
    r = c.get("/console")
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/login"
