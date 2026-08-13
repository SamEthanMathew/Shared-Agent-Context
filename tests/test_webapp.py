"""Serving the built web app.

Two things are easy to get wrong here and both are load-bearing.

The app does client-side routing, so an unmatched ``/app/...`` path must return
``index.html`` — otherwise refreshing a deep link like ``/app/c/<id>`` 404s.

And these routes sit in front of a catch-all mount at the domain root, which is
where the OAuth discovery documents live. Registering them must not shadow it,
or every connected AI client loses the ability to authenticate.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import webapp


@pytest.fixture
def client(wired, monkeypatch):
    from app.main import app

    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    return TestClient(app, follow_redirects=False)


# --- routing --------------------------------------------------------------


@pytest.mark.skipif(not webapp.is_built(), reason="web app not built")
def test_app_root_serves_the_shell(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert "<div id=\"root\">" in r.text


@pytest.mark.skipif(not webapp.is_built(), reason="web app not built")
def test_a_deep_link_serves_the_shell_so_refresh_works(client):
    r = client.get("/app/c/some-context-id")
    assert r.status_code == 200
    assert "<div id=\"root\">" in r.text


@pytest.mark.skipif(not webapp.is_built(), reason="web app not built")
def test_the_shell_is_never_cached(client):
    """It names hashed asset files, so a stale copy pins an old deploy."""
    assert client.get("/app").headers["cache-control"] == "no-store"


@pytest.mark.skipif(not webapp.is_built(), reason="web app not built")
def test_assets_are_cacheable_forever(client):
    import re

    shell = client.get("/app").text
    asset = re.search(r'/app/assets/([^"]+\.js)', shell).group(1)
    r = client.get(f"/app/assets/{asset}")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_a_missing_asset_is_a_404_not_a_crash(client):
    assert client.get("/app/assets/nope-12345.js").status_code == 404


@pytest.mark.parametrize(
    "attempt",
    [
        "..%2F..%2Fdb.py",
        "....//....//app/db.py",
        "%2e%2e%2f%2e%2e%2fmain.py",
        "../../../../../../etc/passwd",
    ],
)
def test_asset_paths_cannot_read_files_outside_the_build(client, attempt):
    """Whether a traversal attempt 404s or falls through to the client-route
    handler is immaterial. What must never happen is a file from outside the
    build directory coming back."""
    r = client.get(f"/app/assets/{attempt}")
    assert r.status_code in (200, 404)
    # Nothing that looks like Python source or a passwd file escaped.
    for leak in ("def ", "import ", "sqlalchemy", "root:x:", "PRIVATE KEY"):
        assert leak not in r.text, f"{attempt} leaked {leak!r}"
    if r.status_code == 200:
        # It served the app shell, which is inert and public.
        assert '<div id="root">' in r.text


def test_the_bare_domain_sends_people_to_the_app(client):
    r = client.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/app"


# --- must not shadow the OAuth surface ------------------------------------
#
# The discovery documents only exist in auth mode, which is also the only mode
# where a real client connects — so this is where the shadowing risk lives.


@pytest.fixture
def auth_client(seed, monkeypatch):
    import importlib

    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://testserver")
    runtime.set_store(seed.store)

    import app.main as main

    importlib.reload(main)
    runtime.set_store(seed.store)
    yield TestClient(main.app, follow_redirects=False)
    importlib.reload(main)


def test_oauth_discovery_still_answers_at_the_root(auth_client):
    """The regression that would silently break every connected AI client."""
    r = auth_client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")


def test_protected_resource_metadata_still_answers(auth_client):
    r = auth_client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    assert set(r.json()["scopes_supported"]) == {"sac.read", "sac.write"}


def test_the_mcp_endpoint_is_still_reachable_and_refuses_anonymous(auth_client):
    """A 401 proves the mount is live; the app routes did not swallow /mcp."""
    r = auth_client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_the_app_routes_win_over_the_root_mount(auth_client):
    r = auth_client.get("/app")
    assert r.status_code in (200, 503)  # shell, or a clear "not built"


def test_health_still_answers(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_the_console_still_works(client):
    """The server-rendered console stays as a fallback surface."""
    r = client.get("/console")
    assert r.status_code in (200, 303)


def test_v1_is_not_shadowed(client):
    """/v1 must still authenticate rather than return the app shell."""
    r = client.get("/v1/contexts")
    assert r.status_code in (401, 403)
    assert "<div id=" not in r.text
