"""Getting out of an unverified account, and the dead ends that had no exit.

Signup creates an account, sends one verification email, and signs the person in
unverified. Everything here is about what happened next: the app opened on an
empty context list, the only action on that screen was refused, there was no way
anywhere in the product to ask for the verification mail again, and a single
rate-limit refusal threw away the OAuth transaction of anyone who had arrived
from a Claude or ChatGPT connector — sending them back to the client to start
"Add connector" over.

What must not change is the other half of the gate. An unverified account may
create its own context, because that reaches nobody; it still may not accept an
invite, join by link, or share, because each of those either takes a context
somebody else owns or sends mail in our name. The attack that protects is pinned
in tests/test_onboarding.py.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import impl, sharing
from app.errors import ForbiddenError
from app.identity import Principal
from app.limits import LIMITS


@pytest.fixture
def web(seed, monkeypatch):
    """Auth + console routers over the seeded store, no network email."""
    import app.runtime as runtime

    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    monkeypatch.setenv("SAC_EMAIL_PROVIDER", "console")
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.example.com")
    runtime.set_store(seed.store)

    app = FastAPI()
    from app.auth.web import router as auth_router
    from app.control import router as console_router

    app.include_router(auth_router)
    app.include_router(console_router)
    return TestClient(app, follow_redirects=False), seed


def _sent(monkeypatch) -> list:
    """Capture outbound mail instead of sending it."""
    box = []
    import app.email as mailer

    monkeypatch.setattr(mailer, "send", lambda e: box.append(e) or True)
    return box


def _token_in(email) -> str:
    """The verification token out of a captured message body."""
    match = re.search(r"token=([^&\s]+)", email.text)
    assert match, email.text
    return match.group(1)


def _signed_in(client, seed, user_id) -> None:
    client.cookies.set("sac_session", seed.store.auth.create_login_session(user_id))


def _newcomer(seed, email="newcomer@example.com"):
    """A registered but never-verified account, as public signup creates."""
    return seed.store.projects.create_user(email, email)


def _txn(seed) -> str:
    """A pending OAuth transaction, as /authorize creates before login."""
    return seed.store.auth.create_transaction(
        client_id="claude-client",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_provided=True,
        scopes=["sac.read", "sac.write"],
        code_challenge="challenge",
        code_challenge_method="S256",
        state="st",
        resource="https://sac.example.com/mcp",
    )


# --- what an unverified account may and may not do --------------------------


def test_an_unverified_account_can_create_its_own_context(seed):
    uid = _newcomer(seed)
    out = impl.create_context(seed.store, Principal(uid, None), "First context")
    assert out["created"] is True
    assert seed.store.projects.get_role(out["active_context"]["id"], uid) == "owner"


def test_an_unverified_account_still_cannot_accept_an_invite(seed):
    uid = _newcomer(seed)
    _id, code = seed.store.invites.create(
        seed.project_id, role="member", created_by_user_id=seed.alice_user_id,
    )
    with pytest.raises(ForbiddenError) as exc:
        sharing.accept_invite(seed.store, code, uid)
    assert "verify" in str(exc.value).lower()
    assert seed.store.projects.get_role(seed.project_id, uid) is None


def test_an_unverified_account_still_cannot_join_by_link(seed):
    uid = _newcomer(seed)
    sharing.set_link_access(seed.store, seed.alice, "edit")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    with pytest.raises(ForbiddenError):
        sharing.join_by_link(seed.store, token, uid)
    assert seed.store.projects.get_role(seed.project_id, uid) is None


def test_an_unverified_account_still_cannot_share(seed):
    """Creating is free, inviting is not: this path sends mail in our name.

    Without the gate a throwaway account could make a context and use it to mail
    any address it liked, which is the whole apparatus of a spam relay.
    """
    uid = _newcomer(seed)
    created = impl.create_context(seed.store, Principal(uid, None), "Theirs")
    identity = seed.store.resolve_identity(
        Principal(uid, None), created["active_context"]["id"]
    )
    with pytest.raises(ForbiddenError) as exc:
        sharing.share_context(seed.store, identity, "stranger@example.com", "edit")
    assert "verify" in str(exc.value).lower()


# --- asking for the verification email again --------------------------------


def test_a_signed_in_user_can_resend_and_the_new_link_works(web, monkeypatch):
    c, seed = web
    box = _sent(monkeypatch)
    uid = _newcomer(seed)
    _signed_in(c, seed, uid)

    r = c.post("/auth/verify/resend")
    assert r.status_code == 303
    assert r.headers["location"] == "/auth/verify/resend?sent=1"
    assert len(box) == 1 and box[0].to == "newcomer@example.com"

    assert c.get(f"/auth/verify?token={_token_in(box[0])}").status_code == 303
    assert seed.store.auth.is_email_verified(uid) is True


def test_a_get_never_sends_mail(web, monkeypatch):
    """The error pages link here, and links get followed by mail scanners."""
    c, seed = web
    box = _sent(monkeypatch)
    _signed_in(c, seed, _newcomer(seed))
    r = c.get("/auth/verify/resend")
    assert r.status_code == 200
    assert "form" in r.text and "post" in r.text
    assert box == []


def test_resend_is_not_an_account_existence_oracle(web, monkeypatch):
    c, seed = web
    box = _sent(monkeypatch)
    _newcomer(seed, "real@example.com")

    real = c.post("/auth/verify/resend", data={"email": "real@example.com"})
    ghost = c.post("/auth/verify/resend", data={"email": "ghost@example.com"})
    verified = c.post("/auth/verify/resend", data={"email": "alice@example.com"})

    # Identical replies for an unverified account, no account, and an account
    # that needs no verification at all.
    assert real.status_code == ghost.status_code == verified.status_code == 303
    assert real.headers["location"] == ghost.headers["location"]
    assert ghost.headers["location"] == verified.headers["location"]
    # Only the one that could use a link got one.
    assert [m.to for m in box] == ["real@example.com"]


def test_a_signed_in_session_outranks_the_typed_address(web, monkeypatch):
    """Otherwise any account is a way to mail a stranger from Osmos."""
    c, seed = web
    box = _sent(monkeypatch)
    _signed_in(c, seed, _newcomer(seed, "mine@example.com"))
    c.post("/auth/verify/resend", data={"email": "victim@example.com"})
    assert [m.to for m in box] == ["mine@example.com"]


def test_resend_is_rate_limited_and_keeps_the_connection(web, monkeypatch):
    c, seed = web
    box = _sent(monkeypatch)
    txn = _txn(seed)
    _signed_in(c, seed, _newcomer(seed))

    limit, _window = LIMITS["verify_resend"]
    for _ in range(limit):
        assert c.post("/auth/verify/resend", data={"txn": txn}).status_code == 303
    refused = c.post("/auth/verify/resend", data={"txn": txn})

    assert len(box) == limit  # the refused attempt sent nothing
    assert refused.status_code == 303
    assert "Too+many" in refused.headers["location"]
    # ...and the pending connection survived the refusal.
    assert f"txn={txn}" in refused.headers["location"]


def test_a_resend_lockout_says_why_on_the_page_it_lands_on(web, monkeypatch, seed):
    """The redirect carries a reason; the page has to accept and show it.

    verify_resend is the tightest bucket in LIMITS, and this is the one screen
    whose entire subject is "the mail never came" — so a refusal that renders as
    the same blank form is a user clicking send again into the same wall.
    """
    c, _ = web
    _sent(monkeypatch)
    _signed_in(c, seed, _newcomer(seed))

    limit, _window = LIMITS["verify_resend"]
    for _ in range(limit):
        c.post("/auth/verify/resend")
    refused = c.post("/auth/verify/resend")

    page = c.get(refused.headers["location"])
    assert page.status_code == 200
    assert "Too many attempts" in page.text


def test_the_resend_link_carries_the_invite_it_was_reached_from(web, monkeypatch):
    """Verifying has to come back to the invite, not to a cold start."""
    c, seed = web
    box = _sent(monkeypatch)
    _signed_in(c, seed, _newcomer(seed))
    c.post("/auth/verify/resend", data={"next": "/invite/abc123"})
    assert "next=/invite/abc123" in box[0].text

    r = c.get(f"/auth/verify?token={_token_in(box[0])}&next=/invite/abc123")
    assert r.headers["location"] == "/invite/abc123"


def test_verifying_lands_in_the_app(web, monkeypatch):
    """With a session to carry, the link goes straight into the product."""
    c, seed = web
    _sent(monkeypatch)
    uid = _newcomer(seed)
    _signed_in(c, seed, uid)
    token = seed.store.auth.create_email_token(uid, "verify", timedelta(hours=1))
    r = c.get(f"/auth/verify?token={token}")
    assert r.status_code == 303
    assert r.headers["location"] == "/app"


def test_verifying_from_the_mailbox_browser_confirms_instead(web, monkeypatch):
    """The ordinary case: mail is opened where the mailbox is, not where the
    session is. That browser cannot be redirected into the app — /v1/me 401s and
    it lands on a bare sign-in form, so the click that worked looks like it did
    nothing."""
    c, seed = web
    _sent(monkeypatch)
    uid = _newcomer(seed)
    token = seed.store.auth.create_email_token(uid, "verify", timedelta(hours=1))

    r = c.get(f"/auth/verify?token={token}")  # no session cookie
    assert r.status_code == 200
    assert "verified" in r.text.lower()
    assert "/auth/login" in r.text
    assert seed.store.auth.is_email_verified(uid) is True


def test_an_expired_verification_link_offers_another(web, seed):
    c, _ = web
    _signed_in(c, seed, _newcomer(seed))
    r = c.get("/auth/verify?token=long-dead-token")
    assert r.status_code == 400
    assert 'action="/auth/verify/resend"' in r.text


# --- a pending connector survives a rate-limit lockout ----------------------


def test_a_signup_lockout_keeps_the_transaction(web):
    """The bug: one lockout and the connector had to be re-added from scratch."""
    c, seed = web
    txn = _txn(seed)
    limit = LIMITS["signup"][0]
    data = {"email": "alice@example.com", "password": "correct-horse-battery",
            "txn": txn}
    for _ in range(limit):
        c.post("/auth/signup", data=data)
    r = c.post("/auth/signup", data=data)
    assert "Too+many" in r.headers["location"]
    assert f"txn={txn}" in r.headers["location"]


def test_a_login_lockout_keeps_the_transaction_and_the_destination(web):
    c, seed = web
    txn = _txn(seed)
    limit = LIMITS["login"][0]
    data = {"email": "nobody@example.com", "password": "wrong-password-here",
            "txn": txn, "next": "/invite/abc123"}
    for _ in range(limit):
        c.post("/auth/login", data=data)
    r = c.post("/auth/login", data=data)
    assert "Too+many" in r.headers["location"]
    assert f"txn={txn}" in r.headers["location"]
    assert "next=/invite/abc123" in r.headers["location"]


def test_a_forgot_password_lockout_keeps_the_transaction(web):
    c, seed = web
    txn = _txn(seed)
    limit = LIMITS["forgot"][0]
    data = {"email": "alice@example.com", "txn": txn}
    for _ in range(limit):
        c.post("/auth/forgot", data=data)
    r = c.post("/auth/forgot", data=data)
    assert "Too+many" in r.headers["location"]
    assert f"txn={txn}" in r.headers["location"]


def test_the_forgot_password_link_carries_the_connection(web):
    c, seed = web
    txn = _txn(seed)
    assert f"/auth/forgot?txn={txn}" in c.get(f"/auth/login?txn={txn}").text


def test_an_sso_email_collision_keeps_the_transaction(web, monkeypatch):
    """Not an error path — this fires when someone who signed up with a password
    later clicks Google, and it used to cost them the connector."""
    from app.auth import sso

    c, seed = web
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("SAC_GOOGLE_CLIENT_SECRET", "test-secret")
    txn = _txn(seed)

    start = c.get(f"/auth/sso/google/start?txn={txn}")
    assert start.status_code == 303
    state = c.cookies["sac_sso"].split("|")[0]

    monkeypatch.setattr(sso, "exchange_code", lambda *a, **k: "access-token")
    monkeypatch.setattr(
        sso, "fetch_profile",
        lambda *a, **k: sso.Profile("g-1", "alice@example.com", "Alice", False),
    )
    r = c.get(f"/auth/sso/google/callback?code=abc&state={state}")
    assert r.status_code == 303
    assert r.headers["location"].startswith("/auth/login")
    assert f"txn={txn}" in r.headers["location"]


# --- every terminal page has a way forward ----------------------------------


def test_an_expired_consent_request_says_what_to_do(web, seed):
    c, _ = web
    _signed_in(c, seed, seed.alice_user_id)
    r = c.get("/auth/consent?txn=long-gone")
    assert r.status_code == 400
    assert "connector again" in r.text
    assert "href=" in r.text


def test_the_resend_page_has_a_way_out_when_signed_in(web, seed):
    """app/control.py routes every unverified console user into this page, and
    signed in it was an h1, a paragraph, a button, and no link anywhere."""
    c, _ = web
    _signed_in(c, seed, _newcomer(seed))
    r = c.get("/auth/verify/resend")
    assert r.status_code == 200
    assert "<a href=" in r.text


def test_an_already_verified_account_is_not_promised_mail(web, seed):
    """resend_submit sends nothing for a verified account, so the page must not
    offer a button that says it will."""
    c, _ = web
    _signed_in(c, seed, seed.alice_user_id)  # verified by the fixture
    r = c.get("/auth/verify/resend")
    assert "already verified" in r.text.lower()
    assert "<a href=" in r.text


def test_a_dead_invite_page_has_a_way_out(web):
    c, _ = web
    r = c.get("/invite/not-a-real-code")
    assert r.status_code == 404
    assert "/auth/login" in r.text


def test_a_dead_share_link_page_has_a_way_out(web):
    c, _ = web
    r = c.get("/c/not-a-real-token")
    assert r.status_code == 404
    assert "/auth/login" in r.text


def test_an_invalid_reset_link_offers_a_new_one(web):
    c, _ = web
    r = c.post("/auth/reset", data={"token": "dead", "password": "a-good-password"})
    assert r.status_code == 400
    assert "/auth/forgot" in r.text


def test_a_refused_invite_offers_the_verification_mail_from_that_page(web, seed):
    c, _ = web
    uid = _newcomer(seed)
    _signed_in(c, seed, uid)
    _id, code = seed.store.invites.create(
        seed.project_id, role="member", created_by_user_id=seed.alice_user_id,
    )
    r = c.post(f"/invite/{code}/accept")
    assert r.status_code == 400
    assert 'action="/auth/verify/resend"' in r.text
    # and the resend comes back to this invite rather than dropping them
    assert f"/invite/{code}" in r.text


def test_a_refused_link_join_offers_the_verification_mail(web, seed):
    c, _ = web
    _signed_in(c, seed, _newcomer(seed))
    sharing.set_link_access(seed.store, seed.alice, "edit")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    r = c.post(f"/c/{token}/join")
    assert r.status_code == 400
    assert 'action="/auth/verify/resend"' in r.text


# --- landing in the product, not in the fallback console --------------------


def test_accepting_an_invite_lands_in_the_app(web, seed):
    c, _ = web
    uid = _newcomer(seed)
    seed.store.auth.mark_email_verified(uid)
    _signed_in(c, seed, uid)
    _id, code = seed.store.invites.create(
        seed.project_id, role="member", created_by_user_id=seed.alice_user_id,
    )
    r = c.post(f"/invite/{code}/accept")
    assert r.status_code == 303
    assert r.headers["location"] == f"/app/c/{seed.project_id}?joined=1"


def test_joining_by_link_lands_in_the_app(web, seed):
    c, _ = web
    uid = _newcomer(seed)
    seed.store.auth.mark_email_verified(uid)
    _signed_in(c, seed, uid)
    sharing.set_link_access(seed.store, seed.alice, "edit")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    r = c.post(f"/c/{token}/join")
    assert r.status_code == 303
    assert r.headers["location"] == f"/app/c/{seed.project_id}?joined=1"
