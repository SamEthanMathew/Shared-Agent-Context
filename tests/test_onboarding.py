"""Onboarding: connector-first signup, and who counts as "having an account".

Two problems this file pins down.

**Account squatting.** Sharing by email granted membership immediately whenever
an account with that address existed — without asking whether anyone had ever
proved they control the mailbox. Anyone could register victim@example.com,
never verify it, and silently receive any context later shared to that address.
An unverified account must therefore be treated as no account at all: the share
becomes an invite, and only whoever can read the mailbox can redeem it.

**The verification step that looks redundant but isn't.** It is tempting to
treat redeeming an invite as proof of mailbox control — the code was emailed to
that address, after all — and skip verification. It is not proof, because
``share_context`` hands the link to the *sharer* too, so links can be delivered
by hand when email is unavailable. Removing the gate would let someone invite an
address, register it, redeem their own code, and walk away holding a verified
account for a mailbox they never controlled — which the sharing path above then
trusts. The two halves of this file are therefore in tension by design, and both
directions are pinned.
"""
from __future__ import annotations

import pytest

from app.api import sharing
from app.errors import ForbiddenError


def _unverified_user(seed, email="newcomer@example.com"):
    """A registered but never-verified account, as public signup creates."""
    return seed.store.projects.create_user(email, email)


# --- an unverified account is not an account --------------------------------


def test_sharing_to_an_unverified_account_creates_an_invite(seed):
    squatter = _unverified_user(seed, "victim@example.com")
    out = sharing.share_context(
        seed.store, seed.alice, "victim@example.com", "edit", base_url="https://sac.test"
    )
    assert out["invited"] is True
    assert out["shared"] is False
    # Crucially, no membership was handed to the unverified account.
    assert seed.store.projects.get_role(seed.project_id, squatter) is None


def test_sharing_to_a_verified_account_still_grants_access_immediately(seed):
    """The common case must stay a single step."""
    carol_email = "carol@example.com"
    out = sharing.share_context(seed.store, seed.alice, carol_email, "view")
    assert out["shared"] is True and out["invited"] is False
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "viewer"


def test_the_squatter_cannot_redeem_the_invite_meant_for_someone_else(seed):
    """Having intercepted nothing, a squatter holds no usable code."""
    squatter = _unverified_user(seed, "squatter@example.com")
    _id, code = seed.store.invites.create(
        seed.project_id, role="member",
        created_by_user_id=seed.alice_user_id, email="realperson@example.com",
    )
    with pytest.raises(ForbiddenError):
        sharing.accept_invite(seed.store, code, squatter)
    assert seed.store.projects.get_role(seed.project_id, squatter) is None


# --- holding an invite code is NOT proof of mailbox control -----------------
#
# It is tempting to treat redemption as proof — the code was emailed to that
# address, after all — and skip the verification step. It isn't proof, because
# `share_context` also returns the link to the sharer so it can be delivered by
# hand. These tests pin the attack that shortcut would open.


def test_redeeming_an_invite_does_not_verify_the_redeemer(seed):
    newcomer = _unverified_user(seed, "newcomer@example.com")
    _id, code = seed.store.invites.create(
        seed.project_id, role="member",
        created_by_user_id=seed.alice_user_id, email="newcomer@example.com",
    )
    with pytest.raises(ForbiddenError) as exc:
        sharing.accept_invite(seed.store, code, newcomer)
    assert "verify" in str(exc.value).lower()
    assert seed.store.auth.is_email_verified(newcomer) is False

    # Verified the normal way, the same invite works.
    seed.store.auth.mark_email_verified(newcomer)
    assert sharing.accept_invite(seed.store, code, newcomer)["ok"] is True


def test_a_sharer_cannot_launder_their_own_invite_into_a_verified_account(seed):
    """The attack the verification gate is actually stopping.

    Alice shares to an address she does not control. Because she is handed the
    link, she could register that address and redeem her own code — and if
    redemption implied verification she would walk away holding a *verified*
    account for someone else's mailbox, which the sharing path trusts.
    """
    out = sharing.share_context(
        seed.store, seed.alice, "victim@example.com", "edit",
        base_url="https://sac.test",
    )
    code = out["invite_link"].rsplit("/", 1)[1]
    squatted = seed.store.projects.create_user("victim@example.com", "V")

    with pytest.raises(ForbiddenError):
        sharing.accept_invite(seed.store, code, squatted)
    assert seed.store.auth.is_email_verified(squatted) is False


def test_an_invite_to_a_different_address_is_still_refused(seed):
    newcomer = _unverified_user(seed, "newcomer@example.com")
    seed.store.auth.mark_email_verified(newcomer)
    _id, code = seed.store.invites.create(
        seed.project_id, role="member",
        created_by_user_id=seed.alice_user_id, email="someoneelse@example.com",
    )
    with pytest.raises(ForbiddenError):
        sharing.accept_invite(seed.store, code, newcomer)


def test_a_link_share_does_not_verify_anybody(seed):
    """A link is not addressed to anyone, so it proves nothing about a mailbox."""
    newcomer = _unverified_user(seed)
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    with pytest.raises(ForbiddenError):
        sharing.join_by_link(seed.store, token, newcomer)
    assert seed.store.auth.is_email_verified(newcomer) is False


# --- connector-first signup -------------------------------------------------


@pytest.fixture
def web(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app as real_app

    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    return TestClient(real_app, follow_redirects=False), wired


def _txn(seed):
    """A pending OAuth transaction, as /authorize creates before login."""
    return seed.store.auth.create_transaction(
        client_id="claude-client",
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_provided=True,
        scopes=["sac.read", "sac.write"],
        code_challenge="challenge",
        code_challenge_method="S256",
        state="st",
        resource="https://sac.test/mcp",
    )


def test_the_login_page_carries_the_oauth_transaction_into_signup(web):
    """Otherwise a new user clicking "create one" silently drops the connection."""
    c, seed = web
    txn = _txn(seed)
    body = c.get(f"/auth/login?txn={txn}").text
    assert f"/auth/signup?txn={txn}" in body


def test_signing_up_mid_oauth_continues_to_consent(web):
    c, seed = web
    txn = _txn(seed)
    r = c.post(
        "/auth/signup",
        data={"email": "brandnew@example.com", "password": "correct-horse-battery",
              "txn": txn},
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/auth/consent?txn={txn}"
    assert seed.store.projects.get_user_by_email("brandnew@example.com")


def test_the_signup_page_carries_the_transaction_back_to_login(web):
    c, seed = web
    txn = _txn(seed)
    body = c.get(f"/auth/signup?txn={txn}").text
    assert f"/auth/login?txn={txn}" in body


def test_signing_up_without_a_transaction_lands_in_the_app(web):
    c, _ = web
    r = c.post(
        "/auth/signup",
        data={"email": "plain@example.com", "password": "correct-horse-battery"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/app"


def test_an_existing_user_signing_up_mid_oauth_keeps_the_transaction(web):
    """They get bounced to sign-in — which must not lose the connection either."""
    c, seed = web
    txn = _txn(seed)
    r = c.post(
        "/auth/signup",
        data={"email": "alice@example.com", "password": "correct-horse-battery",
              "txn": txn},
    )
    assert r.status_code == 303
    assert f"txn={txn}" in r.headers["location"]
