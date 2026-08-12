"""REST /v1 surface via FastAPI TestClient (dev-mode X-SAC-User identity)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(wired):
    # No `with` block: the /v1 and /health routes don't need the MCP session
    # manager, and its lifespan can only start once per process.
    from app.main import app

    return TestClient(app), wired


def _h(email: str) -> dict[str, str]:
    return {"X-SAC-User": email}


def test_health(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_project_info(client):
    c, seed = client
    r = c.get(f"/v1/projects/{seed.project_id}", headers=_h("alice@example.com"))
    assert r.status_code == 200
    body = r.json()
    assert body["project"]["member_count"] == 2
    assert body["identity"]["role"] == "owner"


def test_remember_shared_then_sync_handoff(client):
    c, seed = client
    # alice publishes a shared decision
    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        headers=_h("alice@example.com"),
        json={"kind": "decision", "summary": "Use Supabase Auth and passkeys."},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == 1
    # bob syncs and receives it
    r = c.post(
        f"/v1/projects/{seed.project_id}/context/sync",
        headers=_h("bob@example.com"),
        json={"task": "implement authentication", "session_ref": "claude-main"},
    )
    assert r.status_code == 200
    assert "Supabase" in r.json()["context_text"]


def test_bad_kind_rejected_422(client):
    c, seed = client
    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        headers=_h("alice@example.com"),
        json={"kind": "wizardry", "summary": "nope"},
    )
    assert r.status_code == 422  # pydantic Literal rejects before impl


def test_non_member_gets_403_zero_detail(client):
    c, seed = client
    # carol is not a member of alice/bob's project
    r = c.get(f"/v1/projects/{seed.project_id}", headers=_h("carol@example.com"))
    assert r.status_code == 403
    assert r.json() == {"detail": "forbidden"}


def test_private_isolation_over_rest(client):
    c, seed = client
    # alice writes private; bob lists memories and must not see it
    c.post(
        f"/v1/projects/{seed.project_id}/memories/private",
        headers=_h("alice@example.com"),
        json={"kind": "note", "summary": "Alice private note."},
    )
    r = c.get(
        f"/v1/projects/{seed.project_id}/memories",
        headers=_h("bob@example.com"),
        params={"scope": "private"},
    )
    assert r.status_code == 200
    assert r.json()["memories"] == []


def test_get_memory_404_shape(client):
    c, seed = client
    r = c.get(
        f"/v1/projects/{seed.project_id}/memories/nonexistent",
        headers=_h("alice@example.com"),
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "memory_not_found", "memory_id": "nonexistent"}


def test_supersede_over_rest(client):
    c, seed = client
    old = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        headers=_h("alice@example.com"),
        json={"kind": "decision", "summary": "Use Firebase."},
    ).json()
    new = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        headers=_h("alice@example.com"),
        json={"kind": "decision", "summary": "Use Supabase.", "supersedes": [old["memory"]["id"]]},
    ).json()
    assert new["superseded"] == [old["memory"]["id"]]
