"""The app's banner posts to /auth/verify/resend the way `fetch` does.

/auth/verify/resend is form-and-redirect shaped because it also backs the
server-rendered pages, while web/src/api.js sends no form body and no
Content-Type at all — and for someone sitting under the unverified banner in
web/src/App.jsx, this request is the only way out of it.

Two failures would put them back where they started: rejecting the bodiless
POST as a validation error, and ending on a non-2xx once the browser has
followed the redirect. Either one reaches the user as "resend failed" with
nothing they can do about it, which is the state the banner exists to end.

Every request here signs up first. The banner is only ever on screen for a
signed-in unverified account, and _current_user reads the session cookie alone —
so a cookieless POST takes the anonymous branch with an empty address, sends
nothing, and would still pass both assertions while proving neither.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def web(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app as real_app

    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    monkeypatch.setenv("SAC_EMAIL_PROVIDER", "console")
    return TestClient(real_app, follow_redirects=False)


@pytest.fixture
def sent(monkeypatch) -> list:
    """Capture outbound mail instead of sending it."""
    box: list = []
    import app.email as mailer

    monkeypatch.setattr(mailer, "send", lambda e: box.append(e) or True)
    return box


def _under_the_banner(web, sent: list) -> None:
    """A signed-in unverified account — the only state the banner renders in."""
    r = web.post(
        "/auth/signup",
        data={"email": "banner@example.com", "password": "a-good-password"},
    )
    assert r.status_code == 303, r.text
    assert web.cookies.get("sac_session")
    sent.clear()  # the signup mail; what is under test is the one asked for next


def test_a_bodiless_post_is_not_a_validation_error(web, sent):
    """No form encoding, because api.js has none to send."""
    _under_the_banner(web, sent)
    r = web.post("/auth/verify/resend", headers={"Accept": "application/json"})
    assert r.status_code == 303, r.text
    # The session branch ran: a link was actually minted and mailed.
    assert [m.to for m in sent] == ["banner@example.com"]


def test_the_response_the_spa_ends_on_is_ok(web, sent):
    """fetch follows the 303 itself; what it hands back must not read as an error."""
    _under_the_banner(web, sent)
    r = web.post(
        "/auth/verify/resend",
        headers={"Accept": "application/json"},
        follow_redirects=True,
    )
    assert r.status_code == 200, r.text
