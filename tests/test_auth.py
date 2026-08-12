"""OAuth 2.1 layer: DCR, PKCE code flow, refresh rotation, reuse detection,
connection-revoke → immediate token death, CIMD, bootstrap, login/consent web.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    return verifier, challenge


@pytest.fixture
def auth_env(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.example.com")
    monkeypatch.setenv("SAC_ALLOWED_REDIRECT_HOSTS", "claude.ai,chatgpt.com,example.com")
    previous = runtime.store
    runtime.set_store(seed.store)
    # give alice a password
    seed.store.auth.set_password(seed.alice_user_id, "hunter2")
    yield seed
    runtime.set_store(previous)


def _provider():
    from app.auth.provider import build_provider

    return build_provider()


REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _register_client(provider) -> OAuthClientInformationFull:
    info = OAuthClientInformationFull(
        client_id="sac-testclient",
        redirect_uris=[AnyUrl(REDIRECT)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="sac.read sac.write",
        client_name="Test Claude",
    )
    _run(provider.register_client(info))
    return info


def test_dcr_registers_and_get_client(auth_env):
    provider = _provider()
    _register_client(provider)
    client = _run(provider.get_client("sac-testclient"))
    assert client is not None
    assert str(client.redirect_uris[0]) == REDIRECT


def test_dcr_rejects_disallowed_redirect_host(auth_env):
    from app.auth.provider import _redirect_host_allowed  # noqa

    provider = _provider()
    from mcp.server.auth.provider import RegistrationError

    info = OAuthClientInformationFull(
        client_id="evil",
        redirect_uris=[AnyUrl("https://evil.example.net/cb")],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code"],
        response_types=["code"],
    )
    with pytest.raises(RegistrationError):
        _run(provider.register_client(info))


def _authorize_and_consent(auth_env, provider, client, challenge):
    """Drive authorize → login → consent through the web routes; return the code."""
    params = AuthorizationParams(
        state="xyz",
        scopes=["sac.read", "sac.write"],
        code_challenge=challenge,
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource="https://sac.example.com/mcp",
    )
    login_url = _run(provider.authorize(client, params))
    txn = login_url.split("txn=", 1)[1]

    app = FastAPI()
    from app.auth.web import router

    app.include_router(router)
    c = TestClient(app, follow_redirects=False)
    r = c.post("/auth/login", data={"email": "alice@example.com", "password": "hunter2", "txn": txn})
    assert r.status_code == 303
    r = c.post("/auth/consent", data={"txn": txn, "decision": "approve"})
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith(REDIRECT)
    assert "state=xyz" in location
    code = location.split("code=", 1)[1].split("&", 1)[0]
    return code


def test_full_code_flow_and_token_verification(auth_env):
    provider = _provider()
    client = _register_client(provider)
    _verifier, challenge = _pkce()
    code = _authorize_and_consent(auth_env, provider, client, challenge)

    # SDK would verify PKCE here; provider mints tokens on exchange
    auth_code = _run(provider.load_authorization_code(client, code))
    assert auth_code is not None
    assert auth_code.code_challenge == challenge  # SDK will verify against this
    token = _run(provider.exchange_authorization_code(client, auth_code))
    assert token.access_token.startswith("sac_at_")
    assert token.refresh_token.startswith("sac_rt_")

    # the access token verifies and carries identity claims
    access = _run(provider.load_access_token(token.access_token))
    assert access is not None
    alice = auth_env.store.projects.get_user_by_email("alice@example.com")
    assert access.subject == alice["id"]
    assert access.claims["agent_connection_id"]

    # code is single-use
    assert _run(provider.load_authorization_code(client, code)) is None


def test_refresh_rotation_and_reuse_detection(auth_env):
    provider = _provider()
    client = _register_client(provider)
    _v, challenge = _pkce()
    code = _authorize_and_consent(auth_env, provider, client, challenge)
    auth_code = _run(provider.load_authorization_code(client, code))
    token = _run(provider.exchange_authorization_code(client, auth_code))

    rt1 = token.refresh_token
    loaded = _run(provider.load_refresh_token(client, rt1))
    assert loaded is not None
    new_token = _run(provider.exchange_refresh_token(client, loaded, ["sac.read", "sac.write"]))
    assert new_token.refresh_token != rt1

    # the old refresh token is now revoked
    assert _run(provider.load_refresh_token(client, rt1)) is None
    # replaying the revoked token burns the whole family (containment)
    rt2_loaded = _run(provider.load_refresh_token(client, new_token.refresh_token))
    assert rt2_loaded is None


def test_connection_revoke_kills_token_immediately(auth_env):
    provider = _provider()
    client = _register_client(provider)
    _v, challenge = _pkce()
    code = _authorize_and_consent(auth_env, provider, client, challenge)
    auth_code = _run(provider.load_authorization_code(client, code))
    token = _run(provider.exchange_authorization_code(client, auth_code))

    access = _run(provider.load_access_token(token.access_token))
    assert access is not None
    conn_id = access.claims["agent_connection_id"]

    auth_env.store.projects.revoke_agent_connection(conn_id)
    # the previously-valid access token now fails verification
    assert _run(provider.load_access_token(token.access_token)) is None


def test_deny_redirects_with_error(auth_env):
    provider = _provider()
    client = _register_client(provider)
    _v, challenge = _pkce()
    params = AuthorizationParams(
        state="s1", scopes=["sac.read"], code_challenge=challenge,
        redirect_uri=AnyUrl(REDIRECT), redirect_uri_provided_explicitly=True,
        resource="https://sac.example.com/mcp",
    )
    login_url = _run(provider.authorize(client, params))
    txn = login_url.split("txn=", 1)[1]
    app = FastAPI()
    from app.auth.web import router

    app.include_router(router)
    c = TestClient(app, follow_redirects=False)
    c.post("/auth/login", data={"email": "alice@example.com", "password": "hunter2", "txn": txn})
    r = c.post("/auth/consent", data={"txn": txn, "decision": "deny"})
    assert r.status_code == 303
    assert "error=access_denied" in r.headers["location"]


def test_bad_password_rejected(auth_env):
    app = FastAPI()
    from app.auth.web import router

    app.include_router(router)
    c = TestClient(app, follow_redirects=False)
    r = c.post("/auth/login", data={"email": "alice@example.com", "password": "wrong"})
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


def test_cimd_disabled_without_allowlist(auth_env, monkeypatch):
    # SSRF guard: with no SAC_CIMD_ALLOWED_HOSTS set, CIMD fetching is off.
    monkeypatch.delenv("SAC_CIMD_ALLOWED_HOSTS", raising=False)
    provider = _provider()
    assert _run(provider.get_client("https://chatgpt.com/client.json")) is None


def test_cimd_rejects_disallowed_host(auth_env, monkeypatch):
    monkeypatch.setenv("SAC_CIMD_ALLOWED_HOSTS", "chatgpt.com,openai.com")
    provider = _provider()
    # a URL client_id on a non-allowed host is refused without a network call
    assert _run(provider.get_client("https://evil.example.net/client.json")) is None


def test_cimd_happy_path(auth_env, monkeypatch):
    monkeypatch.setenv("SAC_CIMD_ALLOWED_HOSTS", "chatgpt.com")
    provider = _provider()
    client_id = "https://chatgpt.com/backend-api/mcp/client.json"

    class _Resp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "client_id": client_id,
                "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
                "client_name": "ChatGPT",
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return _Resp()

    monkeypatch.setattr("app.auth.provider.httpx.AsyncClient", _Client)
    client = _run(provider.get_client(client_id))
    assert client is not None
    assert client.client_id == client_id


def test_bootstrap_admin(seed, monkeypatch):
    from app.auth.bootstrap import bootstrap_admin
    from app.stores import SACStore

    monkeypatch.setenv("SAC_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SAC_BOOTSTRAP_ADMIN_PASSWORD", "s3cret")
    store = SACStore("sqlite:///:memory:")
    store.init()
    uid = bootstrap_admin(store)
    assert uid is not None
    assert store.auth.verify_login("admin@example.com", "s3cret")["id"] == uid
    # idempotent: second call is a no-op
    assert bootstrap_admin(store) is None
