"""OAuth scope enforcement.

These exist because a mutation experiment deleted both scope checks — in
``RequestIdentity.require_writer`` and in the ``/v1`` bearer middleware — and the
whole suite still passed. Every other test grants both scopes, so the
missing-scope paths were never exercised. A token limited to ``sac.read`` must
not be able to write.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.errors import ForbiddenError
from app.identity import Principal, RequestIdentity
from app.models import READ_SCOPE, WRITE_SCOPE

# --- identity layer ---------------------------------------------------------


def _identity(scopes: tuple[str, ...], role: str = "member") -> RequestIdentity:
    return RequestIdentity(
        user_id="u1", agent_connection_id="c1", project_id="p1",
        role=role, scopes=scopes,
    )


def test_require_writer_rejects_read_only_scopes():
    with pytest.raises(ForbiddenError) as exc:
        _identity((READ_SCOPE,)).require_writer()
    assert "write scope" in str(exc.value)


def test_require_writer_allows_write_scope():
    _identity((READ_SCOPE, WRITE_SCOPE)).require_writer()  # must not raise


def test_require_writer_still_checks_role_first():
    with pytest.raises(ForbiddenError) as exc:
        _identity((READ_SCOPE, WRITE_SCOPE), role="viewer").require_writer()
    assert "role" in str(exc.value)


def test_require_reader_rejects_missing_read_scope():
    with pytest.raises(ForbiddenError):
        _identity((WRITE_SCOPE,)).require_reader()


def test_no_scopes_means_unscoped_caller_and_is_allowed():
    """Dev-mode/internal identities carry no scopes and are gated by role only."""
    _identity(()).require_writer()
    _identity(()).require_reader()


def test_memory_write_refused_for_read_only_token(seed):
    """End-to-end at the store: a read-only identity cannot publish."""
    read_only = seed.store.resolve_identity(
        Principal(seed.alice_user_id, seed.alice_conn, (READ_SCOPE,)),
        seed.project_id,
    )
    with pytest.raises(ForbiddenError):
        seed.store.memories.remember(
            read_only, scope="shared", kind="note", summary="should be refused"
        )
    # the same identity with the write scope succeeds
    writer = seed.store.resolve_identity(
        Principal(seed.alice_user_id, seed.alice_conn, (READ_SCOPE, WRITE_SCOPE)),
        seed.project_id,
    )
    assert seed.store.memories.remember(
        writer, scope="shared", kind="note", summary="allowed"
    )["memory"].summary == "allowed"


# --- /v1 bearer middleware --------------------------------------------------


@pytest.fixture
def auth_app(seed, monkeypatch):
    """Rebuild the app in auth mode so the bearer middleware is installed.

    app.main configures auth at import time, so it has to be reloaded. The
    module is reloaded again on teardown to leave the default (dev) app in
    place for other tests.
    """
    import app.main as main
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.example.com")
    monkeypatch.setenv("SAC_ALLOWED_REDIRECT_HOSTS", "claude.ai")
    runtime.set_store(seed.store)
    reloaded = importlib.reload(main)
    try:
        yield TestClient(reloaded.app), seed
    finally:
        monkeypatch.undo()
        importlib.reload(main)


def _mint(seed, scopes: list[str]) -> str:
    """Issue a real access token with exactly the given scopes."""
    conn_id = seed.store.projects.create_agent_connection(
        seed.alice_user_id, oauth_client_id="test-client",
        label="scoped test client", granted_scopes=scopes,
    )
    access, _refresh, _ttl = seed.store.auth.create_token_pair(
        "test-client", seed.alice_user_id, conn_id, scopes,
        "https://sac.example.com/mcp",
    )
    return access


def test_v1_read_allowed_with_read_scope(auth_app):
    client, seed = auth_app
    token = _mint(seed, [READ_SCOPE])
    r = client.get(
        f"/v1/projects/{seed.project_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text


def test_v1_write_refused_with_read_only_scope(auth_app):
    client, seed = auth_app
    token = _mint(seed, [READ_SCOPE])
    r = client.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "note", "summary": "should never be stored"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "insufficient_scope"
    assert "insufficient_scope" in r.headers.get("WWW-Authenticate", "")


def test_v1_write_allowed_with_write_scope(auth_app):
    client, seed = auth_app
    token = _mint(seed, [READ_SCOPE, WRITE_SCOPE])
    r = client.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "note", "summary": "stored by a write-scoped token"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_v1_requires_a_token_at_all(auth_app):
    client, seed = auth_app
    r = client.get(f"/v1/projects/{seed.project_id}")
    assert r.status_code == 401
    assert "resource_metadata" in r.headers.get("WWW-Authenticate", "")


# --- discovery metadata must advertise write ---------------------------------


def test_resource_metadata_advertises_write_scope(auth_app):
    """A client picks its scopes from this document.

    The SDK derives scopes_supported from AuthSettings.required_scopes, which is
    intentionally just sac.read, so the unpatched document advertised read-only.
    claude.ai honoured that, requested read-only, and every publish then failed
    with "write scope required" for a member who genuinely had edit access.
    """
    client, _ = auth_app
    r = client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "sac.write" in body["scopes_supported"], (
        "resource metadata must advertise sac.write or clients will request "
        "read-only tokens and be unable to publish"
    )
    assert "sac.read" in body["scopes_supported"]
    assert body["resource"].endswith("/mcp")


def test_authorization_server_metadata_advertises_both_scopes(auth_app):
    client, _ = auth_app
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert set(body["scopes_supported"]) >= {"sac.read", "sac.write"}
