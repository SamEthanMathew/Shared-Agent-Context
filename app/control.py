"""Human control plane.

Makes the shared brain inspectable and correctable (privacy doc §20, PRINCIPLES
#4/#13) and is the only place access can be granted — agents never share.

Pages: your contexts (+ create), one context (memories, members, invites,
audit, retract), and sharing. Login uses the same cookie session as the OAuth
consent pages.
"""
from __future__ import annotations

import html
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .api import sharing
from .auth.web import COOKIE, _page, _wide_page
from .errors import SACError
from .identity import Principal
from .models import READ_SCOPE, ROLE_TO_ACCESS, WRITE_SCOPE
from .runtime import get_store

router = APIRouter(prefix="/console")


def _user(request: Request) -> str | None:
    return get_store().auth.get_login_user(request.cookies.get(COOKIE))


def _esc(v: object) -> str:
    return html.escape(str(v))


def _identity(request: Request, project_id: str):
    """Resolve the caller's identity in a context, or raise ForbiddenError."""
    uid = _user(request)
    return get_store().resolve_identity(
        Principal(uid, None, (READ_SCOPE, WRITE_SCOPE)), project_id
    )


def _forbidden() -> HTMLResponse:
    return HTMLResponse(
        _page("Forbidden", "<h1>Not permitted</h1>"
              '<p class="muted"><a href="/console">Back to your contexts</a></p>'),
        status_code=403,
    )


def _error_page(exc: Exception, back: str) -> HTMLResponse:
    return HTMLResponse(
        _page("Problem", f"<h1>Could not complete that</h1>"
              f"<p>{_esc(exc)}</p>"
              f'<p class="muted"><a href="{_esc(back)}">Back</a></p>'),
        status_code=400,
    )


def _base_url() -> str:
    return (os.getenv("SAC_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


# --- your contexts ----------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def home(request: Request):
    store = get_store()
    uid = _user(request)
    if not uid:
        return RedirectResponse("/auth/login?next=/console", status_code=303)

    contexts = store.projects.list_user_contexts(uid)
    rows = "".join(
        f'<tr><td><a href="/console/c/{_esc(c["id"])}">{_esc(c["name"])}</a></td>'
        f'<td>{_esc(c["access"])}</td><td>r{c["revision"]}</td>'
        f'<td>{c["member_count"]}</td></tr>'
        for c in contexts
    ) or '<tr><td colspan="4" class="muted">No contexts yet — create one below.</td></tr>'

    verified = store.auth.is_email_verified(uid)
    notice = "" if verified else (
        '<p class="notice">Verify your email to create contexts or accept '
        "invitations. Check your inbox for the link.</p>"
    )

    connections = store.projects.list_connections(uid)
    conn_rows = ""
    for c in connections:
        if c["revoked_at"]:
            continue
        bound = store.projects.get_binding(uid, c["id"])
        bound_name = "—"
        if bound:
            project = store.projects.get_project(bound)
            bound_name = project.name if project else "—"
        conn_rows += (
            f'<tr><td>{_esc(c["label"] or c["id"][:8])}</td>'
            f'<td>{_esc(bound_name)}</td>'
            f'<td><form class="inline" method="post" '
            f'action="/auth/connections/{_esc(c["id"])}/revoke">'
            f'<button class="secondary" type="submit">Revoke</button></form></td></tr>'
        )
    conn_rows = conn_rows or '<tr><td colspan="3" class="muted">No connected clients.</td></tr>'

    body = f"""<h1>Your shared contexts</h1>{notice}
<table><tr><th>Context</th><th>Your access</th><th>Revision</th><th>Members</th></tr>
{rows}</table>

<h2>New context</h2>
<form method="post" action="/console/contexts">
<label>Name</label><input name="name" required placeholder="Desktop App">
<label>Description (optional)</label><input name="description">
<button type="submit">Create context</button></form>

<h2>Connected AI clients</h2>
<table><tr><th>Client</th><th>Working in</th><th></th></tr>{conn_rows}</table>
<p class="muted"><form class="inline" method="post" action="/auth/logout">
<button class="secondary" type="submit">Sign out</button></form></p>"""
    return HTMLResponse(_wide_page("Your contexts", body))


@router.post("/contexts")
def create_context(request: Request, name: str = Form(...), description: str = Form("")):
    from .api import impl

    uid = _user(request)
    if not uid:
        return RedirectResponse("/auth/login?next=/console", status_code=303)
    try:
        out = impl.create_context(
            get_store(), Principal(uid, None, (READ_SCOPE, WRITE_SCOPE)),
            name, description=description, make_active=False,
        )
    except SACError as exc:
        return _error_page(exc, "/console")
    return RedirectResponse(
        f"/console/c/{out['active_context']['id']}", status_code=303
    )


# --- one context -------------------------------------------------------------


@router.get("/c/{project_id}", response_class=HTMLResponse)
def context_page(project_id: str, request: Request, joined: str = ""):
    store = get_store()
    uid = _user(request)
    if not uid:
        return RedirectResponse(f"/auth/login?next=/console/c/{project_id}", status_code=303)
    try:
        identity = _identity(request, project_id)
    except SACError:
        return _forbidden()

    project = store.projects.get_project(project_id)
    can_share = identity.role in ("owner", "admin")
    can_write = identity.role in ("owner", "admin", "member")

    welcome = (
        '<p class="notice">You\'ve joined this context. Connect an AI client to '
        'start using it — see <a href="/console">your clients</a>.</p>'
        if joined else ""
    )

    shares = sharing.list_shares(store, identity)
    member_rows = "".join(
        f'<tr><td>{_esc(m["display_name"] or m["email"])}</td>'
        f'<td>{_esc(m["email"])}</td><td>{_esc(m["access"])}</td>'
        + (
            f'<td><form class="inline" method="post" '
            f'action="/console/c/{_esc(project_id)}/revoke">'
            f'<input type="hidden" name="user_id" value="{_esc(m["user_id"])}">'
            f'<button class="secondary" type="submit">Remove</button></form></td>'
            if can_share and m["user_id"] != identity.user_id else "<td></td>"
        )
        + "</tr>"
        for m in shares["members"]
    )
    pending_rows = "".join(
        f'<tr><td>{_esc(i["email"])}</td><td>{_esc(i["access"])}</td>'
        f'<td class="muted">invited</td><td></td></tr>'
        for i in shares["pending_invites"]
    )

    share_form = ""
    if can_share:
        share_form = f"""<h2>Share this context</h2>
<form method="post" action="/console/c/{_esc(project_id)}/share">
<label>Email address</label><input name="email" type="email" required>
<label>Access</label>
<select name="access">
<option value="view">View — can read shared memory</option>
<option value="edit" selected>Edit — can read and publish</option>
<option value="manage">Manage — can also share with others</option>
</select>
<button type="submit">Share</button></form>"""

    def memory_rows(mems):
        out = ""
        for m in mems:
            action = ""
            if can_write and m.status == "active":
                action = (
                    f'<form class="inline" method="post" '
                    f'action="/console/c/{_esc(project_id)}/memories/{_esc(m.id)}/retract">'
                    f'<button class="secondary" type="submit">Retract</button></form>'
                )
            out += (
                f'<tr><td>{_esc(m.kind)}</td><td>{_esc(m.summary)}</td>'
                f'<td>r{m.revision}</td><td>{_esc(m.status)}</td><td>{action}</td></tr>'
            )
        return out or '<tr><td colspan="5" class="muted">Nothing yet.</td></tr>'

    shared_mems = store.memories.list_memories(
        project_id, uid, scope="shared", status=None, limit=200
    )
    private_mems = store.memories.list_memories(
        project_id, uid, scope="private", status="active", limit=200
    )
    audit_rows = "".join(
        f'<tr><td class="muted">{_esc(a["created_at"])}</td>'
        f'<td>{_esc(a["action"])}</td><td class="muted">{_esc(a["entity_type"])}</td></tr>'
        for a in store.audit.recent(project_id, limit=25)
    ) or '<tr><td colspan="3" class="muted">No activity yet.</td></tr>'

    body = f"""<h1>{_esc(project.name)}</h1>{welcome}
<p class="muted">Revision r{project.context_revision} · your access:
{_esc(ROLE_TO_ACCESS.get(identity.role, identity.role))} · slug
<code>{_esc(project.slug)}</code></p>

<h2>Members</h2>
<table><tr><th>Name</th><th>Email</th><th>Access</th><th></th></tr>
{member_rows}{pending_rows}</table>
{share_form}

<h2>Shared memory</h2>
<table><tr><th>Kind</th><th>Summary</th><th>Rev</th><th>Status</th><th></th></tr>
{memory_rows(shared_mems)}</table>

<h2>Your private memory</h2>
<table><tr><th>Kind</th><th>Summary</th><th>Rev</th><th>Status</th><th></th></tr>
{memory_rows(private_mems)}</table>

<h2>Recent activity</h2>
<table><tr><th>When</th><th>Action</th><th>Entity</th></tr>{audit_rows}</table>

<p class="muted"><a href="/console">← All contexts</a></p>"""
    return HTMLResponse(_wide_page(project.name, body))


@router.post("/c/{project_id}/share")
def share(
    project_id: str, request: Request,
    email: str = Form(...), access: str = Form("edit"),
):
    if not _user(request):
        return RedirectResponse("/auth/login", status_code=303)
    try:
        identity = _identity(request, project_id)
        sharing.share_context(
            get_store(), identity, email=email, access=access, base_url=_base_url()
        )
    except SACError as exc:
        return _error_page(exc, f"/console/c/{project_id}")
    return RedirectResponse(f"/console/c/{project_id}", status_code=303)


@router.post("/c/{project_id}/revoke")
def revoke(project_id: str, request: Request, user_id: str = Form(...)):
    if not _user(request):
        return RedirectResponse("/auth/login", status_code=303)
    try:
        sharing.revoke_access(get_store(), _identity(request, project_id), user_id)
    except SACError as exc:
        return _error_page(exc, f"/console/c/{project_id}")
    return RedirectResponse(f"/console/c/{project_id}", status_code=303)


@router.post("/c/{project_id}/memories/{memory_id}/retract")
def retract_memory(project_id: str, memory_id: str, request: Request):
    if not _user(request):
        return RedirectResponse("/auth/login", status_code=303)
    try:
        get_store().memories.retract(_identity(request, project_id), memory_id)
    except SACError as exc:
        return _error_page(exc, f"/console/c/{project_id}")
    return RedirectResponse(f"/console/c/{project_id}", status_code=303)


# --- back-compat: the V1 URL shape ------------------------------------------


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def legacy_project_page(project_id: str, request: Request):
    return RedirectResponse(f"/console/c/{project_id}", status_code=307)
