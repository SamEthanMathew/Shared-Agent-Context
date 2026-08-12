"""Server-rendered auth pages: login, consent, and connection management.

These are the human side of the OAuth flow. The SDK's /authorize handler
redirects the browser here (carrying a transaction id); after the user logs in
and approves, we mint the authorization code and redirect back to the client.
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp.server.auth.provider import construct_redirect_uri

from ..runtime import get_store

router = APIRouter()

COOKIE = "sac_session"


def _secure(request: Request) -> bool:
    # Secure only when actually served over https. Behind Render's proxy the
    # scheme is https once uvicorn runs with --proxy-headers.
    return request.url.scheme == "https"


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:26rem;margin:3rem auto;padding:0 1rem;color:#111}}
h1{{font-size:1.25rem}} .card{{border:1px solid #ddd;border-radius:12px;padding:1.25rem}}
input{{width:100%;padding:.55rem;margin:.35rem 0 .8rem;border:1px solid #ccc;border-radius:8px;box-sizing:border-box}}
button{{padding:.55rem 1rem;border:0;border-radius:8px;background:#111;color:#fff;cursor:pointer}}
button.secondary{{background:#eee;color:#111}} ul{{padding-left:1.1rem}} .muted{{color:#666;font-size:.9rem}}
form.inline{{display:inline}}
</style></head><body><div class="card">{body}</div></body></html>"""


def _current_user(request: Request) -> str | None:
    return get_store().auth.get_login_user(request.cookies.get(COOKIE))


# --- login ------------------------------------------------------------------


@router.get("/auth/login", response_class=HTMLResponse)
def login_form(request: Request, txn: str = "", error: str = "") -> HTMLResponse:
    err = f'<p class="muted" style="color:#b00">{html.escape(error)}</p>' if error else ""
    body = f"""<h1>Sign in to Shared Agent Context</h1>{err}
<form method="post" action="/auth/login">
<input type="hidden" name="txn" value="{html.escape(txn)}">
<label>Email</label><input name="email" type="email" autocomplete="username" required>
<label>Password</label><input name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form>"""
    return HTMLResponse(_page("Sign in", body))


@router.post("/auth/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    txn: str = Form(""),
):
    store = get_store()
    user = store.auth.verify_login(email, password)
    if not user:
        url = f"/auth/login?error=Invalid+credentials"
        if txn:
            url += f"&txn={txn}"
        return RedirectResponse(url, status_code=303)
    sid = store.auth.create_login_session(user["id"])
    target = f"/auth/consent?txn={txn}" if txn else "/auth/connections"
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(
        COOKIE, sid, httponly=True, secure=_secure(request), samesite="lax", path="/"
    )
    return resp


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
