"""Server-rendered auth pages: login, consent, and connection management.

These are the human side of the OAuth flow. The SDK's /authorize handler
redirects the browser here (carrying a transaction id); after the user logs in
and approves, we mint the authorization code and redirect back to the client.
"""
from __future__ import annotations

import html
from datetime import timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import construct_redirect_uri

from ..browser import SESSION_COOKIE, clear_session_cookies, set_session_cookies
from ..models import ROLE_TO_ACCESS
from ..runtime import get_store

router = APIRouter()

COOKIE = SESSION_COOKIE


def _secure(request: Request) -> bool:
    # Secure only when actually served over https. Behind Render's proxy the
    # scheme is https once uvicorn runs with --proxy-headers.
    return request.url.scheme == "https"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_ok(request: Request, bucket: str, extra: str = "") -> bool:
    """Fixed-window rate limit, keyed by bucket + client IP (+ optional field)."""
    from ..limits import LIMITS, RateLimiter

    limit, window = LIMITS.get(bucket, (30, 300))
    key = f"{bucket}:{_client_ip(request)}:{extra}".lower()
    return RateLimiter(get_store().engine).hit(key, limit, window)


def _too_many(target: str) -> RedirectResponse:
    return RedirectResponse(
        f"{target}?error=Too+many+attempts.+Please+wait+and+try+again",
        status_code=303,
    )


_STYLE = """
body{font-family:system-ui,sans-serif;margin:3rem auto;padding:0 1rem;color:#111}
h1{font-size:1.25rem} h2{font-size:1rem;margin-top:1.75rem}
.card{border:1px solid #ddd;border-radius:12px;padding:1.25rem}
input,select{width:100%;padding:.55rem;margin:.35rem 0 .8rem;border:1px solid #ccc;
  border-radius:8px;box-sizing:border-box;font:inherit}
button{padding:.55rem 1rem;border:0;border-radius:8px;background:#111;color:#fff;cursor:pointer;font:inherit}
button.secondary{background:#eee;color:#111}
ul{padding-left:1.1rem} .muted{color:#666;font-size:.9rem}
form.inline{display:inline}
table{width:100%;border-collapse:collapse;margin:.5rem 0 1rem}
th,td{text-align:left;padding:.4rem .5rem;border-bottom:1px solid #eee;vertical-align:top}
th{font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;color:#666}
code{background:#f3f3f3;padding:.1rem .3rem;border-radius:4px}
.notice{background:#fff8e1;border:1px solid #f0e0a0;padding:.6rem .8rem;border-radius:8px}
a{color:#0b57d0}
"""


def _shell(title: str, body: str, max_width: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{_STYLE}body{{max-width:{max_width}}}</style>
</head><body><div class="card">{body}</div></body></html>"""


def _page(title: str, body: str) -> str:
    """Narrow shell for forms (sign-in, consent, invites)."""
    return _shell(title, body, "26rem")


def _wide_page(title: str, body: str) -> str:
    """Wider shell for the console, which renders tables."""
    return _shell(title, body, "56rem")


def _current_user(request: Request) -> str | None:
    return get_store().auth.get_login_user(request.cookies.get(COOKIE))


# --- login ------------------------------------------------------------------


def _safe_next(next_url: str | None) -> str:
    """Only allow same-site relative redirects — never an absolute URL.

    Rejects protocol-relative forms. Note that browsers normalise a backslash
    to a forward slash, so "/\\evil.com" would escape a naive "starts with /"
    check; backslashes and control characters are refused outright.
    """
    if not next_url:
        return ""
    candidate = next_url.strip()
    if not candidate.startswith("/"):
        return ""
    if candidate.startswith("//"):
        return ""
    if "\\" in candidate:
        return ""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate):
        return ""
    return candidate


HOME = "/app"


def _post_login_target(txn: str, next_url: str) -> str:
    """Where to land after a successful sign-in.

    A pending OAuth transaction wins: the user came here to connect a client, so
    finishing that is the whole point. Otherwise an explicit `next` (an invite or
    share link they were following), and failing both, the web app.
    """
    if txn:
        return f"/auth/consent?txn={txn}"
    return _safe_next(next_url) or HOME


def _carry(txn: str, next_url: str) -> str:
    """Query string that preserves an in-flight connection across auth pages.

    A new user arriving from a Claude or ChatGPT connector lands mid-OAuth. If
    the link to the signup page drops `txn`, they finish creating an account and
    the connection they were setting up has silently evaporated.
    """
    parts = []
    if txn:
        parts.append(f"txn={html.escape(txn, quote=True)}")
    safe = _safe_next(next_url)
    if safe:
        parts.append(f"next={html.escape(safe, quote=True)}")
    return ("?" + "&".join(parts)) if parts else ""


@router.get("/auth/login", response_class=HTMLResponse)
def login_form(
    request: Request, txn: str = "", error: str = "", next: str = ""
) -> HTMLResponse:
    err = f'<p class="muted" style="color:#b00">{html.escape(error)}</p>' if error else ""
    nxt = html.escape(_safe_next(next))
    carry = _carry(txn, next)
    connecting = (
        '<p class="notice">Finish signing in to connect your AI client.</p>'
        if txn else ""
    )
    body = f"""<h1>Sign in to Shared Agent Context</h1>{connecting}{err}
{_sso_buttons(carry)}
<form method="post" action="/auth/login">
<input type="hidden" name="txn" value="{html.escape(txn)}">
<input type="hidden" name="next" value="{nxt}">
<label>Email</label><input name="email" type="email" autocomplete="username" required>
<label>Password</label><input name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form>
<p class="muted">No account? <a href="/auth/signup{carry}">Create one</a> ·
<a href="/auth/forgot">Forgot password</a></p>"""
    return HTMLResponse(_page("Sign in", body))


@router.post("/auth/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    txn: str = Form(""),
    next: str = Form(""),
):
    if not _rate_ok(request, "login", email):
        return _too_many("/auth/login")
    store = get_store()
    user = store.auth.verify_login(email, password)
    if not user:
        # One message for every failure mode: unknown email, wrong password,
        # disabled, or locked out. Never confirm whether an account exists.
        url = "/auth/login?error=Invalid+email+or+password"
        if txn:
            url += f"&txn={txn}"
        if _safe_next(next):
            url += f"&next={_safe_next(next)}"
        return RedirectResponse(url, status_code=303)
    sid = store.auth.create_login_session(user["id"])
    resp = RedirectResponse(_post_login_target(txn, next), status_code=303)
    set_session_cookies(resp, sid, secure=_secure(request))
    return resp


@router.post("/auth/logout")
def logout(request: Request):
    sid = request.cookies.get(COOKIE)
    if sid:
        get_store().auth.revoke_login_session(sid)
    resp = RedirectResponse("/auth/login", status_code=303)
    clear_session_cookies(resp)
    return resp


# --- federated sign-in ------------------------------------------------------


SSO_STATE_COOKIE = "sac_sso"


def _sso_buttons(carry: str) -> str:
    """Provider buttons, or nothing at all when none are configured."""
    from .sso import enabled_providers

    providers = enabled_providers()
    if not providers:
        return ""
    links = "".join(
        f'<p><a href="/auth/sso/{p.name}/start{carry}">'
        f'<button type="button" class="secondary" style="width:100%">'
        f"Continue with {html.escape(p.label)}</button></a></p>"
        for p in providers
    )
    return f'{links}<p class="muted" style="text-align:center">or</p>'


def _sso_redirect_uri(request: Request, provider_name: str) -> str:
    """The callback URL, which must match what is registered with the provider."""
    import os

    base = (
        os.getenv("SAC_PUBLIC_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or str(request.base_url).rstrip("/")
    ).rstrip("/")
    return f"{base}/auth/sso/{provider_name}/callback"


@router.get("/auth/sso/{provider_name}/start")
def sso_start(provider_name: str, request: Request, next: str = "", txn: str = ""):
    from .sso import authorize_url, get_provider, new_state

    provider = get_provider(provider_name)
    if provider is None:
        return RedirectResponse(
            "/auth/login?error=That+sign-in+method+is+not+available", status_code=303
        )
    if not _rate_ok(request, "login", provider_name):
        return _too_many("/auth/login")

    state = new_state()
    resp = RedirectResponse(
        authorize_url(provider, _sso_redirect_uri(request, provider.name), state),
        status_code=303,
    )
    # The state is echoed by the provider and compared against this cookie, so a
    # callback that the user did not initiate cannot be replayed at them. The
    # destination rides along in the cookie rather than the state parameter to
    # keep it out of the provider's logs.
    payload = "|".join([state, _safe_next(next), txn])
    resp.set_cookie(
        SSO_STATE_COOKIE, payload, max_age=600, httponly=True,
        secure=_secure(request), samesite="lax", path="/",
    )
    return resp


@router.get("/auth/sso/{provider_name}/callback")
def sso_callback(
    provider_name: str,
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    from .sso import (
        SSOError,
        exchange_code,
        fetch_profile,
        get_provider,
        link_or_create_user,
    )

    def _fail(message: str):
        from urllib.parse import quote_plus

        resp = RedirectResponse(
            f"/auth/login?error={quote_plus(message)}", status_code=303
        )
        resp.delete_cookie(SSO_STATE_COOKIE, path="/")
        return resp

    provider = get_provider(provider_name)
    if provider is None:
        return _fail("That sign-in method is not available")
    if error or not code:
        return _fail("Sign-in was cancelled")

    cookie = request.cookies.get(SSO_STATE_COOKIE) or ""
    expected, _, rest = cookie.partition("|")
    stored_next, _, stored_txn = rest.partition("|")
    import hmac

    if not expected or not hmac.compare_digest(expected, state or ""):
        return _fail("That sign-in link has expired. Please try again")

    store = get_store()
    try:
        token = exchange_code(
            provider, code, _sso_redirect_uri(request, provider.name)
        )
        profile = fetch_profile(provider, token)
        user_id = link_or_create_user(store, provider.name, profile)
    except SSOError as exc:
        return _fail(str(exc))

    sid = store.auth.create_login_session(user_id)
    resp = RedirectResponse(
        _post_login_target(stored_txn, stored_next), status_code=303
    )
    set_session_cookies(resp, sid, secure=_secure(request))
    resp.delete_cookie(SSO_STATE_COOKIE, path="/")
    return resp


# --- signup, verification, password reset -----------------------------------


MIN_PASSWORD = 10


@router.get("/auth/signup", response_class=HTMLResponse)
def signup_form(
    request: Request, error: str = "", next: str = "", txn: str = ""
) -> HTMLResponse:
    err = f'<p class="muted" style="color:#b00">{html.escape(error)}</p>' if error else ""
    nxt = html.escape(_safe_next(next))
    carry = _carry(txn, next)
    connecting = (
        '<p class="notice">Create an account to finish connecting your AI client.</p>'
        if txn else ""
    )
    body = f"""<h1>Create your account</h1>{connecting}{err}
{_sso_buttons(carry)}
<form method="post" action="/auth/signup">
<input type="hidden" name="next" value="{nxt}">
<input type="hidden" name="txn" value="{html.escape(txn)}">
<label>Email</label><input name="email" type="email" autocomplete="username" required>
<label>Password</label><input name="password" type="password" autocomplete="new-password" required>
<p class="muted">At least {MIN_PASSWORD} characters.</p>
<button type="submit">Create account</button></form>
<p class="muted">Already have one? <a href="/auth/login{carry}">Sign in</a></p>"""
    return HTMLResponse(_page("Create account", body))


@router.post("/auth/signup")
def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    txn: str = Form(""),
):
    from .. import email as mailer

    if not _rate_ok(request, "signup"):
        return _too_many("/auth/signup")
    store = get_store()
    address = (email or "").strip().lower()
    nxt = _safe_next(next)
    carry = _carry(txn, next)

    if len(password) < MIN_PASSWORD:
        sep = "&" if carry else "?"
        return RedirectResponse(
            f"/auth/signup{carry}{sep}"
            f"error=Password+must+be+at+least+{MIN_PASSWORD}+characters",
            status_code=303,
        )

    existing = store.projects.get_user_by_email(address)
    if existing:
        # Don't disclose that the address is taken; send them to sign in — still
        # carrying the connection they were in the middle of setting up.
        sep = "&" if carry else "?"
        return RedirectResponse(
            f"/auth/login{carry}{sep}error=Try+signing+in+instead",
            status_code=303,
        )

    user_id = store.projects.create_user(address, display_name=address)
    store.auth.set_password(user_id, password)
    token = store.auth.create_email_token(user_id, "verify", timedelta(hours=24))
    mailer.send_verification(address, token)

    sid = store.auth.create_login_session(user_id)
    resp = RedirectResponse(_post_login_target(txn, next), status_code=303)
    set_session_cookies(resp, sid, secure=_secure(request))
    return resp


@router.get("/auth/verify", response_class=HTMLResponse)
def verify_email(token: str = ""):
    store = get_store()
    user_id = store.auth.consume_email_token(token, "verify")
    if not user_id:
        return HTMLResponse(
            _page("Verification", "<h1>That link is invalid or expired</h1>"
                  '<p class="muted"><a href="/console">Go to your contexts</a></p>'),
            status_code=400,
        )
    store.auth.mark_email_verified(user_id)
    return HTMLResponse(_page(
        "Verified",
        "<h1>Email verified</h1><p>Your account is fully active.</p>"
        '<p><a href="/console">Go to your contexts</a></p>',
    ))


@router.get("/auth/forgot", response_class=HTMLResponse)
def forgot_form(sent: str = ""):
    if sent:
        return HTMLResponse(_page("Check your email", (
            "<h1>Check your email</h1><p class='muted'>If that address has an "
            "account, a reset link is on its way.</p>"
        )))
    body = """<h1>Reset your password</h1>
<form method="post" action="/auth/forgot">
<label>Email</label><input name="email" type="email" required>
<button type="submit">Send reset link</button></form>"""
    return HTMLResponse(_page("Reset password", body))


@router.post("/auth/forgot")
def forgot_submit(request: Request, email: str = Form(...)):
    from .. import email as mailer

    if not _rate_ok(request, "forgot", email):
        return _too_many("/auth/forgot")
    store = get_store()
    user = store.projects.get_user_by_email(email)
    if user:
        token = store.auth.create_email_token(user["id"], "reset", timedelta(hours=1))
        mailer.send_password_reset(user["email"], token)
    # Same response either way — no account-existence oracle.
    return RedirectResponse("/auth/forgot?sent=1", status_code=303)


@router.get("/auth/reset", response_class=HTMLResponse)
def reset_form(token: str = "", error: str = ""):
    err = f'<p class="muted" style="color:#b00">{html.escape(error)}</p>' if error else ""
    body = f"""<h1>Choose a new password</h1>{err}
<form method="post" action="/auth/reset">
<input type="hidden" name="token" value="{html.escape(token)}">
<label>New password</label><input name="password" type="password" autocomplete="new-password" required>
<button type="submit">Set password</button></form>"""
    return HTMLResponse(_page("New password", body))


@router.post("/auth/reset")
def reset_submit(token: str = Form(...), password: str = Form(...)):
    store = get_store()
    if len(password) < MIN_PASSWORD:
        return RedirectResponse(
            f"/auth/reset?token={token}&error=Password+too+short", status_code=303
        )
    user_id = store.auth.consume_email_token(token, "reset")
    if not user_id:
        return HTMLResponse(
            _page("Reset", "<h1>That link is invalid or expired</h1>"), status_code=400
        )
    store.auth.set_password(user_id, password)
    # A password reset also proves control of the mailbox.
    store.auth.mark_email_verified(user_id)
    return HTMLResponse(_page(
        "Password set",
        '<h1>Password updated</h1><p><a href="/auth/login">Sign in</a></p>',
    ))


# --- consent ----------------------------------------------------------------


@router.get("/auth/consent", response_class=HTMLResponse)
def consent_form(request: Request, txn: str = ""):
    store = get_store()
    user_id = _current_user(request)
    if not user_id:
        return RedirectResponse(f"/auth/login?txn={txn}", status_code=303)
    tx = store.auth.get_transaction(txn)
    if not tx:
        return HTMLResponse(_page("Error", "<h1>Request expired</h1>"), status_code=400)
    client = store.auth.get_client(tx["client_id"])
    client_name = (client or {}).get("client_name") or tx["client_id"]
    from urllib.parse import urlparse

    redirect_host = urlparse(tx["redirect_uri"]).hostname or "the client"
    scopes = tx["scopes"] or ["sac.read", "sac.write"]
    scope_items = "".join(
        f"<li>{html.escape(s)}</li>" for s in scopes
    )
    body = f"""<h1>Authorize connection</h1>
<p><b>{html.escape(client_name)}</b> ({html.escape(redirect_host)}) wants to access
Shared Agent Context on your behalf.</p>
<p class="muted">Requested access:</p><ul>{scope_items}</ul>
<form class="inline" method="post" action="/auth/consent">
<input type="hidden" name="txn" value="{html.escape(txn)}">
<input type="hidden" name="decision" value="approve">
<button type="submit">Allow</button></form>
<form class="inline" method="post" action="/auth/consent">
<input type="hidden" name="txn" value="{html.escape(txn)}">
<input type="hidden" name="decision" value="deny">
<button class="secondary" type="submit">Deny</button></form>"""
    return HTMLResponse(_page("Authorize", body))


@router.post("/auth/consent")
def consent_submit(
    request: Request, txn: str = Form(...), decision: str = Form(...)
):
    store = get_store()
    user_id = _current_user(request)
    if not user_id:
        return RedirectResponse(f"/auth/login?txn={txn}", status_code=303)
    tx = store.auth.get_transaction(txn)
    if not tx:
        return HTMLResponse(_page("Error", "<h1>Request expired</h1>"), status_code=400)

    if decision != "approve":
        store.auth.complete_transaction(txn)
        return RedirectResponse(
            construct_redirect_uri(tx["redirect_uri"], error="access_denied", state=tx["state"]),
            status_code=303,
        )

    scopes = tx["scopes"] or ["sac.read", "sac.write"]
    client = store.auth.get_client(tx["client_id"]) or {}
    label = client.get("client_name") or "MCP client"
    provider_hint = client.get("registration_source", "other")

    existing = store.projects.find_active_connection_for_client(user_id, tx["client_id"])
    if existing:
        conn_id = existing["id"]
    else:
        conn_id = store.projects.create_agent_connection(
            user_id, oauth_client_id=tx["client_id"], label=label,
            provider_hint=provider_hint, client_type="mcp", granted_scopes=scopes,
        )

    code = store.auth.create_code(
        client_id=tx["client_id"],
        user_id=user_id,
        agent_connection_id=conn_id,
        redirect_uri=tx["redirect_uri"],
        redirect_uri_provided=tx["redirect_uri_provided"],
        scopes=scopes,
        code_challenge=tx["code_challenge"],
        code_challenge_method=tx["code_challenge_method"],
        resource=tx["resource"],
    )
    store.auth.complete_transaction(txn)
    return RedirectResponse(
        construct_redirect_uri(tx["redirect_uri"], code=code, state=tx["state"]),
        status_code=303,
    )


# --- connection management --------------------------------------------------


@router.get("/auth/connections", response_class=HTMLResponse)
def connections(request: Request):
    store = get_store()
    user_id = _current_user(request)
    if not user_id:
        return RedirectResponse("/auth/login", status_code=303)
    conns = store.projects.list_connections(user_id)
    items = []
    for c in conns:
        status = "revoked" if c["revoked_at"] else "active"
        revoke = ""
        if not c["revoked_at"]:
            revoke = (
                f'<form class="inline" method="post" action="/auth/connections/{c["id"]}/revoke">'
                f'<button class="secondary" type="submit">Revoke</button></form>'
            )
        items.append(
            f'<li>{html.escape(c["label"] or c["id"])} '
            f'<span class="muted">({status})</span> {revoke}</li>'
        )
    body = f"<h1>Connected clients</h1><ul>{''.join(items) or '<li class=muted>None</li>'}</ul>"
    return HTMLResponse(_page("Connections", body))


# --- accepting a shared context ---------------------------------------------


@router.get("/invite/{code}", response_class=HTMLResponse)
def invite_landing(code: str, request: Request):
    """Show what's being shared, then sign in or sign up to accept."""
    store = get_store()
    invite = store.invites.get_by_code(code)
    if invite is None:
        return HTMLResponse(
            _page("Invite", "<h1>This invite is invalid, expired, or already used</h1>"),
            status_code=404,
        )
    context_name = store.invites.get_project_name(invite["project_id"])
    access = ROLE_TO_ACCESS.get(invite["role"], invite["role"])
    uid = _current_user(request)
    if uid:
        body = f"""<h1>Join '{html.escape(context_name)}'</h1>
<p>You've been given <b>{html.escape(access)}</b> access to this shared context.</p>
<form method="post" action="/invite/{html.escape(code)}/accept">
<button type="submit">Accept and join</button></form>"""
        return HTMLResponse(_page("Join context", body))

    nxt = f"/invite/{code}"
    body = f"""<h1>Join '{html.escape(context_name)}'</h1>
<p>You've been given <b>{html.escape(access)}</b> access to this shared context.</p>
<p class="muted">Sign in or create an account to accept.</p>
<p><a href="/auth/signup?next={html.escape(nxt)}"><button type="button">Create account</button></a>
<a href="/auth/login?next={html.escape(nxt)}"><button type="button" class="secondary">Sign in</button></a></p>"""
    return HTMLResponse(_page("Join context", body))


@router.post("/invite/{code}/accept")
def invite_accept(code: str, request: Request):
    from ..api.sharing import accept_invite
    from ..errors import SACError

    store = get_store()
    if not _rate_ok(request, "invite_accept"):
        return HTMLResponse(
            _page("Slow down", "<h1>Too many attempts</h1>"), status_code=429
        )
    uid = _current_user(request)
    if not uid:
        return RedirectResponse(f"/auth/login?next=/invite/{code}", status_code=303)
    try:
        result = accept_invite(store, code, uid)
    except SACError as exc:
        return HTMLResponse(
            _page("Invite", f"<h1>Could not join</h1><p>{html.escape(str(exc))}</p>"),
            status_code=400,
        )
    # Land on the context, and nudge toward connecting an AI client.
    return RedirectResponse(f"/console/c/{result['project_id']}?joined=1", status_code=303)


# --- joining by share link --------------------------------------------------


@router.get("/c/{token}", response_class=HTMLResponse)
def link_landing(token: str, request: Request):
    """The URL people paste into a group chat.

    Deliberately shows the context name and access level before asking anyone to
    sign in: a person deciding whether to join should know what they are joining.
    Nothing about the context's *contents* is revealed.
    """
    store = get_store()
    project = store.projects.get_by_link_token(token)
    if project is None:
        return HTMLResponse(
            _page("Link", "<h1>This link is invalid or no longer active</h1>"
                  '<p class="muted">Ask whoever shared it for a new one.</p>'),
            status_code=404,
        )
    access = project.link_access
    verb = "view" if access == "view" else "view and edit"
    uid = _current_user(request)
    if uid:
        role = store.projects.get_role(project.id, uid)
        if role:
            return RedirectResponse(f"/console/c/{project.id}", status_code=303)
        body = f"""<h1>Join '{html.escape(project.name)}'</h1>
<p>Anyone with this link can <b>{verb}</b> this shared context.</p>
<form method="post" action="/c/{html.escape(token)}/join">
<button type="submit">Join this context</button></form>"""
        return HTMLResponse(_page("Join context", body))

    nxt = f"/c/{token}"
    body = f"""<h1>Join '{html.escape(project.name)}'</h1>
<p>Anyone with this link can <b>{verb}</b> this shared context.</p>
<p class="muted">Sign in or create an account to join.</p>
<p><a href="/auth/signup?next={html.escape(nxt)}"><button type="button">Create account</button></a>
<a href="/auth/login?next={html.escape(nxt)}"><button type="button" class="secondary">Sign in</button></a></p>"""
    return HTMLResponse(_page("Join context", body))


@router.post("/c/{token}/join")
def link_join(token: str, request: Request):
    from ..api.sharing import join_by_link
    from ..errors import SACError

    if not _rate_ok(request, "invite_accept"):
        return HTMLResponse(
            _page("Slow down", "<h1>Too many attempts</h1>"), status_code=429
        )
    uid = _current_user(request)
    if not uid:
        return RedirectResponse(f"/auth/login?next=/c/{token}", status_code=303)
    try:
        result = join_by_link(get_store(), token, uid)
    except SACError as exc:
        return HTMLResponse(
            _page("Link", f"<h1>Could not join</h1><p>{html.escape(str(exc))}</p>"),
            status_code=400,
        )
    return RedirectResponse(f"/console/c/{result['project_id']}?joined=1", status_code=303)


@router.post("/auth/connections/{conn_id}/revoke")
def revoke_connection(conn_id: str, request: Request):
    store = get_store()
    user_id = _current_user(request)
    if not user_id:
        return RedirectResponse("/auth/login", status_code=303)
    conn = store.projects.get_agent_connection(conn_id)
    if conn and conn["user_id"] == user_id:
        store.projects.revoke_agent_connection(conn_id)
    return RedirectResponse("/auth/connections", status_code=303)
