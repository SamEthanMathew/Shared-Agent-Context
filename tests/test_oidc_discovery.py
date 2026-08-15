"""Discovery documents, including the one ChatGPT actually asks for.

ChatGPT does not follow the RFC 9728 `resource_metadata` pointer in the 401's
WWW-Authenticate header. On a 401 from /mcp it probes
/.well-known/openid-configuration, and when that 404s it gives up with
"ExceptionGroup: unhandled errors in a TaskGroup", which names nothing a user
could act on.

That failure was invisible from inside the product: /mcp worked, both OAuth
documents were served, every tool passed its own tests, and the connector still
could not be used from one of the two clients this exists for. Only the access
log showed it — four POST /mcp -> 401 followed by four
GET /.well-known/openid-configuration -> 404 from ChatGPT's Azure range.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(seed, monkeypatch):
    """The app in auth mode, where the discovery routes exist at all.

    app.main reads auth configuration at import time, so it has to be reloaded,
    and reloaded again afterwards to leave the default dev app for other tests.
    Same approach as tests/test_scopes.py.
    """
    import app.main as main
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.example.com")
    monkeypatch.setenv("SAC_ALLOWED_REDIRECT_HOSTS", "claude.ai")
    runtime.set_store(seed.store)
    reloaded = importlib.reload(main)
    try:
        yield TestClient(reloaded.app)
    finally:
        monkeypatch.undo()
        importlib.reload(main)


DOCS = [
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
    "/.well-known/oauth-protected-resource/mcp",
]


@pytest.mark.parametrize("path", DOCS)
def test_discovery_document_is_served(auth_client, path):
    r = auth_client.get(path)
    assert r.status_code == 200, f"{path} -> {r.status_code}; a client cannot discover us"
    assert r.json(), f"{path} returned an empty document"


def test_openid_configuration_matches_the_oauth_document(auth_client):
    """One builder feeds both, so they cannot drift.

    If these diverged, a client that discovered us one way would be sent to
    different endpoints than one that discovered us the other way.
    """
    a = auth_client.get("/.well-known/oauth-authorization-server").json()
    b = auth_client.get("/.well-known/openid-configuration").json()
    assert a == b


@pytest.mark.parametrize("field", [
    "issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint",
])
def test_openid_configuration_carries_what_a_client_needs(auth_client, field):
    body = auth_client.get("/.well-known/openid-configuration").json()
    assert body.get(field), f"discovery is missing {field}"


def test_we_do_not_claim_openid_features_we_lack(auth_client):
    """Serving the OAuth document here is an alias, not a claim to be an OP.

    There is no ID token and no key set. Advertising jwks_uri or signing
    algorithms would point clients at endpoints that do not exist, which is a
    worse failure than the 404 this route replaced.
    """
    body = auth_client.get("/.well-known/openid-configuration").json()
    for absent in ("jwks_uri", "id_token_signing_alg_values_supported", "userinfo_endpoint"):
        assert absent not in body, f"{absent} is advertised but not implemented"
