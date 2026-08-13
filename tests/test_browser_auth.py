"""Session-cookie authentication for /v1, so a browser SPA can call the API.

Until now /v1 accepted only OAuth bearer tokens, which are issued to AI clients.
A first-party web app has no bearer token — it has the login cookie. Accepting
that cookie introduces an *ambient* credential, which is exactly what CSRF
exploits, so every mutating cookie-authenticated call must also carry a token
the attacker's origin cannot read.

Two rules define the boundary these tests defend:

1. A bearer token is not ambient, so it never needs CSRF.
2. A cookie IS ambient, so it always does — and cookie auth must not become a
   way to bypass the scope checks that constrain agents.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app.browser import CSRF_COOKIE, CSRF_HEADER, csrf_token_for


@pytest.fixture
def client(seed, monkeypatch):
    """A real app instance in auth mode, with the seeded store behind it.

    Auth mode matters: it is the only mode where the /v1 middleware is active,
    and therefore the only mode where these rules are enforced.
    """
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    # https because RFC 8414 requires an HTTPS issuer; the host matches the
    # TestClient's so same-origin checks behave as they do in a browser.
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://testserver")
    monkeypatch.delenv("SAC_DEFAULT_PROJECT_ID", raising=False)
    runtime.set_store(seed.store)
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")

    import app.main as main

    importlib.reload(main)
    runtime.set_store(seed.store)
    with TestClient(main.app, follow_redirects=False) as c:
        yield c, seed
    importlib.reload(main)


def _sign_in(c) -> str:
    r = c.post(
        "/auth/login",
        data={"email": "alice@example.com", "password": "correct-horse-battery"},
    )
    assert r.status_code == 303, r.text
    assert c.cookies.get("sac_session"), "login must set the session cookie"
    return c.cookies.get(CSRF_COOKIE) or ""


# --- the cookie is accepted at all ------------------------------------------


def test_unauthenticated_v1_is_still_refused(client):
    c, _ = client
    r = c.get("/v1/contexts")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_session_cookie_authenticates_a_read(client):
    c, seed = client
    _sign_in(c)
    r = c.get("/v1/contexts")
    assert r.status_code == 200, r.text
    names = [x["name"] for x in r.json()["contexts"]]
    assert names == ["Shared Desktop App"]


def test_login_issues_a_csrf_cookie_the_page_can_read(client):
    """Double-submit only works if the front end can read the cookie back."""
    c, _ = client
    r = c.post(
        "/auth/login",
        data={"email": "alice@example.com", "password": "correct-horse-battery"},
    )
    cookies = r.headers.get_list("set-cookie")
    session_line = next(x for x in cookies if x.startswith("sac_session="))
    csrf_line = next(x for x in cookies if x.startswith(f"{CSRF_COOKIE}="))
    # The session cookie must stay hidden from scripts; the CSRF one must not.
    assert "httponly" in session_line.lower()
    assert "httponly" not in csrf_line.lower()


def test_csrf_cookie_is_bound_to_the_session(client):
    """A token lifted from another session must not validate for this one."""
    c, seed = client
    _sign_in(c)
    sid = c.cookies["sac_session"]
    assert c.cookies[CSRF_COOKIE] == csrf_token_for(sid)
    assert csrf_token_for("some-other-session") != csrf_token_for(sid)


# --- CSRF enforcement on mutations ------------------------------------------


def test_cookie_write_without_csrf_header_is_refused(client):
    c, seed = client
    _sign_in(c)
    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        json={"kind": "decision", "summary": "Should never be stored."},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "csrf_required"


def test_cookie_write_with_valid_csrf_header_succeeds(client):
    c, seed = client
    token = _sign_in(c)
    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        json={"kind": "decision", "summary": "Stored through the browser API."},
        headers={CSRF_HEADER: token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_cookie_write_with_a_forged_csrf_header_is_refused(client):
    c, seed = client
    _sign_in(c)
    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        json={"kind": "decision", "summary": "Forged."},
        headers={CSRF_HEADER: csrf_token_for("attacker-guess")},
    )
    assert r.status_code == 403


def test_csrf_is_required_for_every_mutating_method(client):
    c, seed = client
    _sign_in(c)
    share = f"/v1/contexts/{seed.project_id}/shares/{seed.bob_user_id}"
    calls = (
        ("POST", "/v1/contexts", {"name": "x"}),
        ("PATCH", share, {"access": "view"}),
        ("DELETE", share, None),
    )
    for method, path, body in calls:
        r = c.request(method, path, json=body)
        assert r.status_code == 403, f"{method} {path} accepted without CSRF"
        assert r.json()["detail"] == "csrf_required"


def test_reads_do_not_require_csrf(client):
    """GETs are safe and must stay frictionless, or the SPA cannot boot."""
    c, seed = client
    _sign_in(c)
    for path in (
        "/v1/contexts",
        f"/v1/projects/{seed.project_id}",
        f"/v1/projects/{seed.project_id}/memories",
    ):
        assert c.get(path).status_code == 200, path


# --- cookie auth must not widen what a caller may do ------------------------


def test_a_cookie_cannot_reach_another_users_context(client):
    """The cookie authenticates a user; it does not grant membership."""
    c, seed = client
    _sign_in(c)
    r = c.get(f"/v1/projects/{seed.other_project_id}")
    assert r.status_code == 403


def test_bearer_still_works_and_needs_no_csrf(client):
    """Regression guard: adding cookie support must not disturb agents."""
    c, seed = client
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE
    import app.main as main

    # Stand in for a verified token by patching the provider's verifier.
    class _Access:
        subject = seed.alice_user_id
        scopes = [READ_SCOPE, WRITE_SCOPE]
        claims = {"agent_connection_id": seed.alice_conn, "connection_label": "ChatGPT"}

    async def _load(token):
        return _Access() if token == "good-token" else None

    main.provider.load_access_token = _load  # type: ignore[assignment]

    r = c.post(
        f"/v1/projects/{seed.project_id}/memories/shared",
        json={"kind": "decision", "summary": "Written by an agent."},
        headers={"Authorization": "Bearer good-token"},
    )
    assert r.status_code == 200, r.text


def test_bearer_wins_over_a_cookie_on_the_same_request(client):
    """An explicit credential must outrank the ambient one."""
    c, seed = client
    _sign_in(c)
    import app.main as main

    async def _load(token):
        return None

    main.provider.load_access_token = _load  # type: ignore[assignment]
    # A present-but-invalid bearer must fail, not silently fall back to the cookie.
    r = c.get("/v1/contexts", headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401


# --- /v1/me, the SPA's bootstrap --------------------------------------------


def test_me_returns_the_user_and_their_contexts(client):
    c, seed = client
    _sign_in(c)
    r = c.get("/v1/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["email_verified"] is True
    assert [x["name"] for x in body["contexts"]] == ["Shared Desktop App"]
    assert body["csrf_token"] == c.cookies[CSRF_COOKIE]


def test_me_refuses_an_anonymous_caller(client):
    c, _ = client
    assert c.get("/v1/me").status_code == 401


def test_me_reissues_the_csrf_cookie_when_it_is_missing(client):
    """A session can outlive its CSRF cookie; booting the SPA must repair that."""
    c, seed = client
    _sign_in(c)
    sid = c.cookies["sac_session"]
    c.cookies.delete(CSRF_COOKIE)
    r = c.get("/v1/me")
    assert r.status_code == 200
    assert r.json()["csrf_token"] == csrf_token_for(sid)
    assert c.cookies[CSRF_COOKIE] == csrf_token_for(sid)


def test_logout_invalidates_the_api_session(client):
    c, seed = client
    _sign_in(c)
    assert c.get("/v1/me").status_code == 200
    c.post("/auth/logout")
    assert c.get("/v1/me").status_code == 401
