"""Sign in with Google / GitHub.

The network calls are stubbed — what is worth testing is the identity logic, and
it has two sharp edges.

**Matching by email is a takeover risk.** If we attach a provider login to an
existing local account whenever the emails match, then any provider that lets
someone claim an unverified address becomes a way into somebody else's contexts.
So an email match is honoured only when the provider says it verified the
address, and refused otherwise.

**A provider's assertion can stand in for our verification email.** When Google
or GitHub vouches for the mailbox, making the user click our own link asks them
to prove the same fact twice.
"""
from __future__ import annotations

import pytest

from app.auth import sso
from app.auth.sso import Profile, SSOError


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_SECRET", "test-secret")
    return sso.GOOGLE


# --- configuration ----------------------------------------------------------


def test_providers_are_absent_until_configured(monkeypatch):
    for var in (
        "SAC_GOOGLE_CLIENT_ID", "SAC_GOOGLE_CLIENT_SECRET",
        "SAC_GITHUB_CLIENT_ID", "SAC_GITHUB_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    assert sso.enabled_providers() == []
    assert sso.get_provider("google") is None


def test_a_half_configured_provider_stays_disabled(monkeypatch):
    """An id without a secret cannot complete a flow, so don't offer it."""
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_ID", "only-the-id")
    monkeypatch.delenv("SAC_GOOGLE_CLIENT_SECRET", raising=False)
    assert sso.get_provider("google") is None


def test_configured_provider_is_offered(google):
    assert sso.get_provider("google") is sso.GOOGLE
    assert sso.GOOGLE in sso.enabled_providers()


def test_authorize_url_carries_the_state_and_asks_which_account(google):
    url = sso.authorize_url(google, "https://sac.test/auth/sso/google/callback", "st8")
    assert url.startswith("https://accounts.google.com/")
    assert "state=st8" in url
    assert "client_id=test-client" in url
    # Without this Google silently reuses whichever session the browser has.
    assert "prompt=select_account" in url


def test_state_values_are_unpredictable():
    assert len({sso.new_state() for _ in range(50)}) == 50
    assert len(sso.new_state()) >= 24


# --- linking and account creation -------------------------------------------


def _profile(email="fresh@example.com", verified=True, account_id="g-1"):
    return Profile(
        account_id=account_id, email=email,
        display_name="Fresh Person", email_verified=verified,
    )


def test_a_new_verified_profile_creates_a_verified_account(seed):
    user_id = sso.link_or_create_user(seed.store, "google", _profile())
    user = seed.store.projects.get_user(user_id)
    assert user["email"] == "fresh@example.com"
    assert user["display_name"] == "Fresh Person"
    # The provider vouched for the mailbox, so no second round trip.
    assert seed.store.auth.is_email_verified(user_id) is True


def test_a_new_unverified_profile_creates_an_unverified_account(seed):
    user_id = sso.link_or_create_user(
        seed.store, "google", _profile("unverified@example.com", verified=False)
    )
    assert seed.store.auth.is_email_verified(user_id) is False


def test_signing_in_again_returns_the_same_account(seed):
    first = sso.link_or_create_user(seed.store, "google", _profile())
    again = sso.link_or_create_user(seed.store, "google", _profile())
    assert again == first


def test_the_link_is_matched_on_the_provider_id_not_the_email(seed):
    """People change their email at the provider; the account is still theirs."""
    first = sso.link_or_create_user(seed.store, "google", _profile())
    renamed = sso.link_or_create_user(
        seed.store, "google", _profile(email="renamed@example.com")
    )
    assert renamed == first
    # No second account was created for the new address.
    assert seed.store.projects.get_user_by_email("renamed@example.com") is None


def test_a_verified_provider_email_attaches_to_an_existing_account(seed):
    """Alice already has a password account; Google sign-in should reach it."""
    user_id = sso.link_or_create_user(
        seed.store, "google", _profile(email="alice@example.com")
    )
    assert user_id == seed.alice_user_id


def test_an_unverified_provider_email_must_not_attach_to_an_existing_account(seed):
    """The account-takeover case: refuse rather than link."""
    with pytest.raises(SSOError) as exc:
        sso.link_or_create_user(
            seed.store, "google",
            _profile(email="alice@example.com", verified=False),
        )
    assert "not verified" in str(exc.value)
    # And no link was recorded that a later sign-in could ride on.
    assert seed.store.auth.get_sso_identity("google", "g-1") is None


def test_a_profile_with_no_email_is_refused(seed):
    with pytest.raises(SSOError):
        sso.link_or_create_user(seed.store, "google", _profile(email=""))


def test_two_providers_can_reach_the_same_account(seed):
    """Connecting a second provider must not fork the account."""
    google_id = sso.link_or_create_user(
        seed.store, "google", _profile(account_id="g-9")
    )
    github_id = sso.link_or_create_user(
        seed.store, "github", _profile(account_id="gh-9")
    )
    assert github_id == google_id
    providers = {i["provider"] for i in seed.store.auth.list_sso_identities(google_id)}
    assert providers == {"google", "github"}


def test_the_same_provider_account_cannot_be_linked_to_two_users(seed):
    """The uniqueness constraint is what makes the identity lookup meaningful."""
    sso.link_or_create_user(seed.store, "google", _profile(account_id="g-solo"))
    linked = seed.store.auth.get_sso_identity("google", "g-solo")
    seed.store.auth.link_sso_identity(
        seed.bob_user_id, "google", "g-solo", "fresh@example.com"
    )
    # Re-linking updates the existing row rather than inserting a duplicate.
    rows = [
        i for i in seed.store.auth.list_sso_identities(seed.bob_user_id)
        if i["provider"] == "google"
    ]
    assert seed.store.auth.get_sso_identity("google", "g-solo") == linked
    assert rows == []


def test_unlinking_removes_the_provider(seed):
    user_id = sso.link_or_create_user(seed.store, "google", _profile())
    seed.store.auth.unlink_sso_identity(user_id, "google")
    assert seed.store.auth.list_sso_identities(user_id) == []
    assert seed.store.auth.get_sso_identity("google", "g-1") is None


# --- the web flow -----------------------------------------------------------


@pytest.fixture
def web(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app as real_app

    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_SECRET", "test-secret")
    return TestClient(real_app, follow_redirects=False), wired


def test_the_login_page_offers_a_configured_provider(web):
    c, _ = web
    body = c.get("/auth/login").text
    assert "Continue with Google" in body
    assert "/auth/sso/google/start" in body


def test_the_login_page_hides_unconfigured_providers(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app as real_app

    for var in ("SAC_GOOGLE_CLIENT_ID", "SAC_GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    c = TestClient(real_app, follow_redirects=False)
    body = c.get("/auth/login").text
    assert "Continue with" not in body


def test_start_redirects_to_the_provider_and_stores_state(web):
    c, _ = web
    r = c.get("/auth/sso/google/start")
    assert r.status_code == 303
    assert r.headers["location"].startswith("https://accounts.google.com/")
    assert c.cookies.get("sac_sso")


def test_start_carries_the_oauth_transaction_through_the_provider(web):
    """A connector-first user must land back on consent, not the console."""
    c, seed = web
    txn = seed.store.auth.create_transaction(
        client_id="claude", redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_provided=True, scopes=["sac.read"], code_challenge="ch",
        code_challenge_method="S256", state="s", resource="https://sac.test/mcp",
    )
    r = c.get(f"/auth/sso/google/start?txn={txn}")
    assert r.status_code == 303
    # The destination rides in the cookie, not the state sent to Google.
    assert txn in c.cookies["sac_sso"]
    assert txn not in r.headers["location"]


def test_an_unknown_provider_is_refused(web):
    c, _ = web
    r = c.get("/auth/sso/nosuchprovider/start")
    assert r.status_code == 303
    assert "not+available" in r.headers["location"]


def test_a_callback_with_a_mismatched_state_is_refused(web):
    """Blocks a login-CSRF replay: the user must have started this flow."""
    c, _ = web
    c.get("/auth/sso/google/start")
    r = c.get("/auth/sso/google/callback?code=abc&state=not-the-stored-state")
    assert r.status_code == 303
    assert "/auth/login?error=" in r.headers["location"]
    assert not c.cookies.get("sac_session")


def test_a_callback_with_no_state_cookie_is_refused(web):
    c, _ = web
    r = c.get("/auth/sso/google/callback?code=abc&state=anything")
    assert r.status_code == 303
    assert not c.cookies.get("sac_session")


def test_a_cancelled_sign_in_is_reported_not_crashed(web):
    c, _ = web
    c.get("/auth/sso/google/start")
    r = c.get("/auth/sso/google/callback?error=access_denied")
    assert r.status_code == 303
    assert "cancelled" in r.headers["location"].lower()


def test_a_successful_callback_signs_the_user_in(web, monkeypatch):
    c, seed = web
    r = c.get("/auth/sso/google/start")
    state = c.cookies["sac_sso"].split("|")[0]

    monkeypatch.setattr(
        "app.auth.sso.exchange_code", lambda *a, **k: "provider-token"
    )
    monkeypatch.setattr(
        "app.auth.sso.fetch_profile",
        lambda *a, **k: Profile("g-web", "webuser@example.com", "Web User", True),
    )

    r = c.get(f"/auth/sso/google/callback?code=abc&state={state}")
    assert r.status_code == 303
    assert r.headers["location"] == "/app"
    assert c.cookies.get("sac_session")
    user = seed.store.projects.get_user_by_email("webuser@example.com")
    assert user is not None
    assert seed.store.auth.is_email_verified(user["id"]) is True


def test_a_provider_failure_lands_on_login_with_a_message(web, monkeypatch):
    c, _ = web
    c.get("/auth/sso/google/start")
    state = c.cookies["sac_sso"].split("|")[0]

    def _boom(*a, **k):
        raise SSOError("the sign-in provider rejected the request")

    monkeypatch.setattr("app.auth.sso.exchange_code", _boom)
    r = c.get(f"/auth/sso/google/callback?code=abc&state={state}")
    assert r.status_code == 303
    assert "/auth/login?error=" in r.headers["location"]
    assert not c.cookies.get("sac_session")
