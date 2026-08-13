"""Signup, email verification, password reset, and login hardening."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import sharing
from app.errors import ForbiddenError
from app.identity import Principal
from app.models import READ_SCOPE, WRITE_SCOPE


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


# --- signup -----------------------------------------------------------------


def test_signup_creates_account_and_logs_in(web, monkeypatch):
    c, seed = web
    box = _sent(monkeypatch)
    r = c.post("/auth/signup", data={"email": "new@example.com", "password": "a-good-password"})
    assert r.status_code == 303
    assert r.headers["location"] == "/console"
    assert c.cookies.get("sac_session")
    user = seed.store.projects.get_user_by_email("new@example.com")
    assert user is not None
    # verification email went out, and the account is NOT yet verified
    assert len(box) == 1 and "verify" in box[0].subject.lower()
    assert seed.store.auth.is_email_verified(user["id"]) is False


def test_signup_rejects_short_password(web):
    c, _ = web
    r = c.post("/auth/signup", data={"email": "new@example.com", "password": "short"})
    assert r.status_code == 303
    assert "at+least" in r.headers["location"]


def test_signup_with_existing_email_does_not_disclose(web):
    c, _ = web
    r = c.post("/auth/signup", data={"email": "alice@example.com", "password": "a-good-password"})
    assert r.status_code == 303
    # sent to sign-in with a neutral message, never "email already taken"
    assert r.headers["location"].startswith("/auth/login")
    assert "taken" not in r.headers["location"].lower()
    assert "exists" not in r.headers["location"].lower()


# --- verification -----------------------------------------------------------


def test_verify_link_marks_account_verified(web, monkeypatch):
    c, seed = web
    _sent(monkeypatch)
    c.post("/auth/signup", data={"email": "new@example.com", "password": "a-good-password"})
    user = seed.store.projects.get_user_by_email("new@example.com")
    token = seed.store.auth.create_email_token(user["id"], "verify", timedelta(hours=1))
    r = c.get(f"/auth/verify?token={token}")
    assert r.status_code == 200
    assert seed.store.auth.is_email_verified(user["id"]) is True


def test_verify_token_is_single_use(web, seed):
    token = seed.store.auth.create_email_token(seed.alice_user_id, "verify", timedelta(hours=1))
    c, _ = web
    assert c.get(f"/auth/verify?token={token}").status_code == 200
    assert c.get(f"/auth/verify?token={token}").status_code == 400


def test_expired_verify_token_rejected(web, seed):
    token = seed.store.auth.create_email_token(
        seed.alice_user_id, "verify", timedelta(seconds=-1)
    )
    c, _ = web
    assert c.get(f"/auth/verify?token={token}").status_code == 400


def test_unverified_user_cannot_create_context(seed):
    from app.api import impl

    uid = seed.store.projects.create_user("unverified@example.com", "U")
    with pytest.raises(ForbiddenError) as exc:
        impl.create_context(seed.store, Principal(uid, None), "Sneaky")
    assert "verify your email" in str(exc.value)


def test_unverified_user_cannot_accept_share(seed):
    out = sharing.share_context(
        seed.store,
        seed.store.resolve_identity(
            Principal(seed.alice_user_id, seed.alice_conn, (READ_SCOPE, WRITE_SCOPE)),
            seed.project_id,
        ),
        email="newcomer@example.com", access="edit",
    )
    code = out["invite_link"].rsplit("/", 1)[1]
    uid = seed.store.projects.create_user("newcomer@example.com", "N")
    with pytest.raises(ForbiddenError):
        sharing.accept_invite(seed.store, code, uid)
    # once verified, the same invite works
    seed.store.auth.mark_email_verified(uid)
    assert sharing.accept_invite(seed.store, code, uid)["ok"] is True


def test_verification_gate_can_be_disabled(seed, monkeypatch):
    from app.api import impl

    monkeypatch.setenv("SAC_REQUIRE_VERIFIED_EMAIL", "0")
    uid = seed.store.projects.create_user("unverified@example.com", "U")
    assert impl.create_context(seed.store, Principal(uid, None), "Fine")["ok"] is True


# --- password reset ---------------------------------------------------------


def test_forgot_password_sends_link_and_does_not_disclose(web, monkeypatch):
    c, _ = web
    box = _sent(monkeypatch)
    r1 = c.post("/auth/forgot", data={"email": "alice@example.com"})
    r2 = c.post("/auth/forgot", data={"email": "ghost@example.com"})
    # identical response for a real and an unknown address
    assert r1.status_code == r2.status_code == 303
    assert r1.headers["location"] == r2.headers["location"]
    assert len(box) == 1  # only the real account got mail


def test_reset_sets_new_password_and_verifies(web, seed):
    c, _ = web
    token = seed.store.auth.create_email_token(seed.alice_user_id, "reset", timedelta(hours=1))
    r = c.post("/auth/reset", data={"token": token, "password": "brand-new-password"})
    assert r.status_code == 200
    assert seed.store.auth.verify_login("alice@example.com", "brand-new-password")
    assert seed.store.auth.is_email_verified(seed.alice_user_id) is True


def test_reset_token_single_use(web, seed):
    c, _ = web
    token = seed.store.auth.create_email_token(seed.alice_user_id, "reset", timedelta(hours=1))
    c.post("/auth/reset", data={"token": token, "password": "brand-new-password"})
    r = c.post("/auth/reset", data={"token": token, "password": "another-password-x"})
    assert r.status_code == 400


def test_verify_token_cannot_be_used_as_reset(web, seed):
    c, _ = web
    token = seed.store.auth.create_email_token(seed.alice_user_id, "verify", timedelta(hours=1))
    r = c.post("/auth/reset", data={"token": token, "password": "brand-new-password"})
    assert r.status_code == 400


# --- login hardening --------------------------------------------------------


def test_login_lockout_after_repeated_failures(seed):
    auth = seed.store.auth
    auth.set_password(seed.alice_user_id, "correct-horse-battery")
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert auth.verify_login("alice@example.com", "wrong") is None
    # correct password is now refused while locked
    assert auth.verify_login("alice@example.com", "correct-horse-battery") is None


def test_successful_login_clears_failures(seed):
    auth = seed.store.auth
    auth.set_password(seed.alice_user_id, "correct-horse-battery")
    auth.verify_login("alice@example.com", "wrong")
    assert auth.verify_login("alice@example.com", "correct-horse-battery")
    user = seed.store.projects.get_user(seed.alice_user_id)
    assert int(user["failed_login_count"]) == 0


def test_login_failure_message_is_identical_for_unknown_and_wrong(web, seed):
    c, _ = web
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")
    r1 = c.post("/auth/login", data={"email": "alice@example.com", "password": "wrong"})
    r2 = c.post("/auth/login", data={"email": "ghost@example.com", "password": "wrong"})
    assert r1.headers["location"] == r2.headers["location"]


def test_logout_revokes_session(web, seed):
    c, _ = web
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")
    c.post("/auth/login", data={"email": "alice@example.com", "password": "correct-horse-battery"})
    assert c.get("/console").status_code == 200
    r = c.post("/auth/logout")
    assert r.status_code == 303
    # session no longer valid -> bounced to login
    c.cookies.clear()
    assert c.get("/console").status_code == 303


def test_login_next_param_only_allows_relative(web, seed):
    c, _ = web
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")
    r = c.post("/auth/login", data={
        "email": "alice@example.com", "password": "correct-horse-battery",
        "next": "https://evil.example.net/steal",
    })
    # open redirect refused; falls back to the console
    assert r.headers["location"] == "/console"


def test_login_next_param_honours_relative_path(web, seed):
    c, _ = web
    seed.store.auth.set_password(seed.alice_user_id, "correct-horse-battery")
    r = c.post("/auth/login", data={
        "email": "alice@example.com", "password": "correct-horse-battery",
        "next": "/invite/abc123",
    })
    assert r.headers["location"] == "/invite/abc123"


# --- invite landing / acceptance through the web ----------------------------


def test_invite_landing_and_accept_flow(web, seed, monkeypatch):
    c, _ = web
    _sent(monkeypatch)
    out = sharing.share_context(
        seed.store,
        seed.store.resolve_identity(
            Principal(seed.alice_user_id, seed.alice_conn, (READ_SCOPE, WRITE_SCOPE)),
            seed.project_id,
        ),
        email="joiner@example.com", access="view",
    )
    code = out["invite_link"].rsplit("/", 1)[1]

    # anonymous: sees what's offered and is asked to sign in or sign up
    r = c.get(f"/invite/{code}")
    assert r.status_code == 200
    assert "Shared Desktop App" in r.text
    assert "view" in r.text

    # sign up through the invite, verify, then accept
    c.post("/auth/signup", data={"email": "joiner@example.com", "password": "a-good-password"})
    joiner = seed.store.projects.get_user_by_email("joiner@example.com")
    seed.store.auth.mark_email_verified(joiner["id"])
    r = c.post(f"/invite/{code}/accept")
    assert r.status_code == 303
    assert seed.store.projects.get_role(seed.project_id, joiner["id"]) == "viewer"
