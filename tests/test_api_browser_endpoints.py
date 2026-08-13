"""The /v1 endpoints the web app needs beyond the agent-facing ones.

Retracting memory, reading the activity feed, and managing connected AI clients
all existed only as server-rendered console pages. The front end needs them as
JSON, and pointing a client at a context — the thing an agent does with
``sac_use_context`` — needs to be doable by a person who would rather click.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def api(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.browser import CSRF_COOKIE, CSRF_HEADER
    from app.main import app as real_app

    seed = wired
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")
    seed.store.auth.set_password(seed.bob_user_id, "correct-horse-battery")

    client = TestClient(real_app, follow_redirects=False)

    def sign_in(email="alice@example.com"):
        client.cookies.clear()
        r = client.post(
            "/auth/login", data={"email": email, "password": "correct-horse-battery"}
        )
        assert r.status_code == 303
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]

    sign_in()
    return client, seed, sign_in


# --- retracting memory ------------------------------------------------------


def test_retract_removes_a_memory_from_the_active_set(api):
    c, seed, _ = api
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Rescind me."
    )
    mid = out["memory"].id

    r = c.post(f"/v1/projects/{seed.project_id}/memories/{mid}/retract")
    assert r.status_code == 200, r.text
    assert r.json()["retracted"] is True

    listed = c.get(f"/v1/projects/{seed.project_id}/memories").json()["memories"]
    assert mid not in [m["id"] for m in listed]


def test_a_viewer_cannot_retract(api):
    """Read-only access must stay read-only through the web app too."""
    c, seed, sign_in = api
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Alice's."
    )
    seed.store.projects.add_membership(
        seed.project_id, seed.bob_user_id, role="viewer"
    )
    sign_in("bob@example.com")
    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/{out['memory'].id}/retract"
    )
    assert r.status_code == 403


# --- activity feed ----------------------------------------------------------


def test_activity_lists_audited_events_with_readable_actors(api):
    c, seed, _ = api
    c.post(
        f"/v1/contexts/{seed.project_id}/shares",
        json={"email": "carol@example.com", "access": "view"},
    )
    r = c.get(f"/v1/contexts/{seed.project_id}/activity")
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    assert any(e["action"] == "context.share" for e in events)
    # Actors are shown as emails, not raw uuids.
    assert any(e["actor"] == "alice@example.com" for e in events)


def test_activity_is_refused_to_a_non_member(api):
    c, seed, _ = api
    r = c.get(f"/v1/contexts/{seed.other_project_id}/activity")
    assert r.status_code == 403


def test_activity_hides_per_sync_noise(api):
    """context.compile fires on every sync and would bury the real history.

    Its detail has a dedicated surface — the snapshots endpoint — so the feed
    keeps to governance events.
    """
    c, seed, _ = api
    from app.context import compile_context

    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.alice_user_id, "chat-noise"
    )
    for task in ("one", "two", "three"):
        compile_context(seed.store, seed.alice, session, task)

    actions = [
        e["action"]
        for e in c.get(f"/v1/contexts/{seed.project_id}/activity").json()["events"]
    ]
    assert "context.compile" not in actions
    assert "source.read" not in actions


def test_activity_still_fills_a_page_when_noise_is_filtered(api):
    """Filtering after the limit would return a near-empty page."""
    c, seed, _ = api
    from app.context import compile_context

    session = seed.store.sessions.get_or_create(
        seed.project_id, seed.alice_user_id, "chat-fill"
    )
    for n in range(12):
        compile_context(seed.store, seed.alice, session, f"task {n}")
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="note", summary=f"note {n}"
        )

    events = c.get(f"/v1/contexts/{seed.project_id}/activity?limit=10").json()["events"]
    assert len(events) == 10
    assert all(e["action"] == "memory.create" for e in events)


# --- connected AI clients ---------------------------------------------------


def test_connections_lists_the_callers_clients_only(api):
    c, seed, _ = api
    r = c.get("/v1/connections")
    assert r.status_code == 200, r.text
    ids = [x["id"] for x in r.json()["connections"]]
    assert seed.alice_conn in ids
    assert seed.bob_conn not in ids


def test_connections_reports_which_context_each_client_uses(api):
    c, seed, _ = api
    seed.store.projects.set_binding(
        seed.alice_user_id, seed.project_id, seed.alice_conn
    )
    conns = c.get("/v1/connections").json()["connections"]
    mine = next(x for x in conns if x["id"] == seed.alice_conn)
    assert mine["context_id"] == seed.project_id
    assert mine["context_name"] == "Shared Desktop App"


def test_a_person_can_point_a_client_at_a_context_by_name(api):
    """The click-driven equivalent of the agent calling sac_use_context."""
    c, seed, _ = api
    r = c.put(
        f"/v1/connections/{seed.alice_conn}/context",
        json={"context": "Shared Desktop App"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["context_id"] == seed.project_id
    assert (
        seed.store.projects.get_binding(seed.alice_user_id, seed.alice_conn)
        == seed.project_id
    )


def test_binding_refuses_a_context_the_caller_is_not_in(api):
    """A raw id from another tenant must not become a binding."""
    c, seed, _ = api
    r = c.put(
        f"/v1/connections/{seed.alice_conn}/context",
        json={"context": seed.other_project_id},
    )
    assert r.status_code == 403
    assert seed.store.projects.get_binding(seed.alice_user_id, seed.alice_conn) is None


def test_binding_refuses_someone_elses_connection(api):
    c, seed, _ = api
    r = c.put(
        f"/v1/connections/{seed.bob_conn}/context",
        json={"context": "Shared Desktop App"},
    )
    assert r.status_code == 404


def test_revoking_a_connection_marks_it_revoked(api):
    c, seed, _ = api
    r = c.post(f"/v1/connections/{seed.alice_conn}/revoke")
    assert r.status_code == 200, r.text
    conns = c.get("/v1/connections").json()["connections"]
    assert next(x for x in conns if x["id"] == seed.alice_conn)["revoked"] is True


def test_cannot_revoke_someone_elses_connection(api):
    c, seed, _ = api
    r = c.post(f"/v1/connections/{seed.bob_conn}/revoke")
    assert r.status_code == 404
    assert seed.store.projects.get_agent_connection(seed.bob_conn)["revoked_at"] is None


# --- all of it still needs CSRF ---------------------------------------------


def test_the_new_mutations_are_csrf_protected(api):
    c, seed, _ = api
    from app.browser import CSRF_HEADER

    del c.headers[CSRF_HEADER]
    for method, path, body in (
        ("POST", f"/v1/connections/{seed.alice_conn}/revoke", None),
        ("PUT", f"/v1/connections/{seed.alice_conn}/context", {"context": "x"}),
    ):
        r = c.request(method, path, json=body)
        assert r.status_code == 403, f"{method} {path}"
        assert r.json()["detail"] == "csrf_required"
