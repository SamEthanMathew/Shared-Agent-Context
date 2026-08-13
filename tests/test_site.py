"""The marketing site, served by the app itself.

Osmos is a hosted product, so the front door and the product live on one origin:
``withosmos.com`` shows the site to a stranger and the app to whoever is signed
in. That makes these routes part of the deployed service rather than a separate
static host, and it puts them in front of the catch-all MCP mount at the domain
root.

Three risks follow, and every test here defends one of them.

1. **Shadowing the OAuth surface.** ``/`` is where RFC 8414/9728 discovery lives.
   A route registered carelessly at the root breaks every connected Claude and
   ChatGPT at once, and nothing in the site's own behaviour would reveal it.
2. **Serving files that are not the site.** The pages are read off disk, so the
   path handling has to be as careful as the app's build-asset route already is.
3. **Saying things that are no longer true.** The site used to describe a
   repository you clone and host. Copy that tells a visitor to run a server, or
   that names the tools an agent calls, is a defect now — so the few claims that
   would mislead a buyer are asserted here rather than left to review.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from app import webapp
from app.billing.plans import FREE, PLANS, PRO_ANNUAL_CENTS, PRO_MONTHLY_CENTS


@pytest.fixture
def client(wired, monkeypatch):
    from app.main import app

    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    return TestClient(app, follow_redirects=False)


# --- the front door ---------------------------------------------------------


def test_the_bare_domain_shows_the_site_to_a_signed_out_visitor(client):
    """The root used to redirect to /app, which showed a stranger a login form.

    A hosted product's home page is the thing that explains it.
    """
    r = client.get("/")
    assert r.status_code == 200
    assert "Different people. Different agents." in r.text


def test_a_signed_in_visitor_is_sent_straight_to_the_app(client, wired):
    """Someone with a session has already been sold to; the pitch is a detour."""
    sid = wired.store.auth.create_login_session(wired.alice_user_id)
    client.cookies.set("sac_session", sid)
    r = client.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/app"


def test_a_stale_session_cookie_still_gets_the_site(client):
    """An expired or forged cookie must not produce an error page at the root.

    It resolves to nobody, and nobody is a visitor.
    """
    client.cookies.set("sac_session", "not-a-real-session")
    r = client.get("/")
    assert r.status_code == 200
    assert "Different people. Different agents." in r.text


@pytest.mark.parametrize("path", ["/get-started", "/security", "/pricing"])
def test_every_marketing_page_is_served(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "<title>" in r.text


def test_the_site_can_be_read_without_javascript(client):
    """The pages are files, not a bundle: no build step stands between a
    request and the words. A JS failure must not be able to blank the page."""
    body = client.get("/").text
    assert "<h1" in body and "Osmos" in body


# --- what the site says -----------------------------------------------------


def test_the_homepage_sends_people_to_signup_rather_than_to_a_repository(client):
    """Every primary call to action is the product, not the source.

    The whole funnel used to terminate on a GitHub link, which sells nothing.
    """
    body = client.get("/").text
    assert "/auth/signup" in body
    assert "Start free" in body


def test_signing_in_is_reachable_from_the_site(client):
    """A returning customer arriving at the front door needs a way through it."""
    assert "/auth/login" in client.get("/").text


@pytest.mark.parametrize(
    "internal",
    [
        "sac_sync_context",   # the tool names are the agent's business, not the reader's
        "PKCE",
        "dynamic client registration",
        "SQLite",
        "Streamable HTTP",
        "token budget",
    ],
)
def test_the_homepage_does_not_teach_the_visitor_how_it_works(client, internal):
    """You connect an assistant, pick a context, and work. Everything else is
    an implementation detail that costs a reader attention and buys nothing."""
    assert internal not in client.get("/").text


@pytest.mark.parametrize(
    "runbook",
    ["git clone", "pip install", "uvicorn", "render.yaml", "DATABASE_URL"],
)
def test_getting_started_is_not_a_self_hosting_runbook(client, runbook):
    """It used to open "One person runs the service". Nobody runs it now."""
    assert runbook not in client.get("/get-started").text


def test_getting_started_names_the_connector_url(client):
    """The one string a person has to copy correctly for any of this to work."""
    body = client.get("/get-started").text
    assert "https://withosmos.com/mcp" in body
    assert "/auth/signup" in body


def test_the_site_never_claims_data_lives_wherever_you_run_it(client):
    """It was true of a repository and is false of a hosted service. A wrong
    answer about where data lives is the worst kind of wrong on this site."""
    for path in ("/", "/security", "/pricing", "/get-started"):
        assert "Wherever you run it" not in client.get(path).text


def test_privacy_claims_that_the_memory_never_leaves(client):
    """New and now true: there is no embedding or summarisation model in the
    path, so nothing is sent anywhere to make retrieval work. It is the
    strongest privacy claim the product has, and it must be findable."""
    body = client.get("/security").text
    assert "third party" in body


# --- pricing must agree with the code that charges --------------------------


def test_pricing_states_the_prices_the_product_actually_charges(client):
    """Bound to plans.py on purpose: a price changed in one place and not the
    other is a promise the checkout will not keep."""
    body = client.get("/pricing").text
    assert f"${PRO_MONTHLY_CENTS // 100}" in body
    assert f"${PRO_ANNUAL_CENTS // 100}" in body


def test_pricing_states_the_free_allowances(client, free_plan_limits):
    """Read from the plan itself, so a limit that moves cannot leave the page
    quoting the old number to someone deciding whether to pay."""
    free = PLANS[FREE]
    body = client.get("/pricing").text
    assert str(free.max_contexts) in body
    assert str(free.max_members) in body
    assert str(free.max_agents) in body


def test_pricing_promises_nothing_is_deleted_for_a_billing_reason(client):
    """The property that makes a downgrade safe to risk, and it is implemented:
    exceeding a limit restricts, it never destroys."""
    body = client.get("/pricing").text
    assert "never deleted" in body or "nothing is ever deleted" in body.lower()
    assert "14" in body  # the grace period, not a shutoff


# --- serving the files ------------------------------------------------------


@pytest.mark.parametrize(
    "asset",
    ["/styles.css", "/osmos.css", "/theme.js", "/motion.js", "/assets/favicon.svg"],
)
def test_the_sites_own_assets_are_served(client, asset):
    r = client.get(asset)
    assert r.status_code == 200, asset
    assert r.content


def test_a_missing_site_asset_is_a_404_not_a_crash(client):
    assert client.get("/nothing-here-12345.css").status_code == 404


@pytest.mark.parametrize(
    "attempt",
    [
        "..%2F..%2Fapp%2Fdb.py",
        "....//....//app/db.py",
        "%2e%2e%2f%2e%2e%2fmain.py",
        "../../../../../../etc/passwd",
    ],
)
@pytest.mark.parametrize("prefix", ["/assets/", "/"])
def test_site_paths_cannot_read_files_outside_the_site(client, prefix, attempt):
    """Whether a traversal attempt 404s or falls through to another handler is
    immaterial. What must never happen is a file from outside website/site
    coming back."""
    r = client.get(f"{prefix}{attempt}")
    assert r.status_code in (200, 404, 405, 406)
    for leak in ("import ", "sqlalchemy", "root:x:", "PRIVATE KEY", "def "):
        assert leak not in r.text, f"{prefix}{attempt} leaked {leak!r}"


def test_the_pages_are_not_pinned_in_a_cache(client):
    """The site is edited far more often than the app is deployed, and none of
    its files carry a content hash, so a long cache would serve last week's
    copy of a page that has since changed its price."""
    for path in ("/", "/pricing"):
        assert "immutable" not in client.get(path).headers.get("cache-control", "")


def test_the_root_page_is_never_cached_by_a_shared_cache(client):
    """It answers differently for a signed-in visitor, so a cached copy would
    show one person's redirect — or the pitch — to everyone behind it."""
    assert "no-store" in client.get("/").headers.get("cache-control", "")


# --- the regression that breaks every connected client ----------------------
#
# The discovery documents live at the domain root, which is exactly where the
# site now lives too. These run in auth mode because that is the only mode a
# real client connects in.


@pytest.fixture
def auth_client(seed, monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://testserver")
    runtime.set_store(seed.store)

    import app.main as main

    importlib.reload(main)
    runtime.set_store(seed.store)
    yield TestClient(main.app, follow_redirects=False)
    importlib.reload(main)


def test_oauth_discovery_still_answers_under_the_site(auth_client):
    r = auth_client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200, r.text
    assert r.json()["token_endpoint"].endswith("/token")


def test_protected_resource_metadata_still_answers_under_the_site(auth_client):
    r = auth_client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    assert set(r.json()["scopes_supported"]) == {"sac.read", "sac.write"}


def test_the_mcp_endpoint_is_still_reachable_under_the_site(auth_client):
    """A 401 proves the mount is live and the site routes did not swallow it."""
    r = auth_client.post(
        "/mcp",
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


@pytest.mark.skipif(not webapp.is_built(), reason="web app not built")
def test_the_app_still_answers_at_its_own_path(auth_client):
    r = auth_client.get("/app")
    assert r.status_code == 200
    assert '<div id="root">' in r.text


def test_the_site_does_not_shadow_the_api(client):
    """/v1 must still authenticate rather than return a marketing page."""
    r = client.get("/v1/contexts")
    assert r.status_code in (401, 403)
    assert "<h1" not in r.text


# --- CSP: the server-rendered pages must not rely on inline CSS --------------


def test_auth_pages_carry_no_inline_css(wired):
    """CSP blocks inline styles, and the failure is completely silent.

    app/main.py sends `Content-Security-Policy: default-src 'self'`. With no
    `style-src` of its own that falls back to `'self'`, which forbids both
    `<style>` blocks and `style=` attributes. The HTML stays valid and the
    server returns 200 — the CSS simply never applies, so every sign-in,
    consent and invite page renders as unstyled text. Nothing logs an error.

    This shipped to production unnoticed, which is exactly why it is a test and
    not a code review note.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app, follow_redirects=False)
    for path in ("/auth/login", "/auth/signup", "/auth/forgot"):
        body = c.get(path).text
        assert "<style>" not in body, f"{path} has an inline <style> block"
        assert 'style="' not in body, f"{path} has an inline style attribute"
        assert '<link rel="stylesheet"' in body, f"{path} loads no stylesheet"


def test_the_auth_stylesheet_is_served(wired):
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).get("/auth/osmos.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    # The width classes the shell depends on must actually be in it.
    assert ".wrap.narrow" in r.text and ".wrap.wide" in r.text


def test_the_csp_permits_a_same_origin_stylesheet(wired):
    """Guard the other direction: if someone later tightens the CSP so that a
    same-origin stylesheet is refused, these pages go unstyled again."""
    from fastapi.testclient import TestClient

    from app.main import app

    csp = TestClient(app).get("/auth/login").headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp or "style-src" in csp
    assert "'unsafe-inline'" not in csp, "CSP was loosened instead of fixing the cause"
