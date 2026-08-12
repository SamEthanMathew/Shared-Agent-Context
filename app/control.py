"""Human control plane — server-rendered project pages.

Makes the shared brain inspectable and correctable (privacy doc §20, PRINCIPLES
#4/#13): projects, members, connected clients, shared + private memories with a
retract action, the audit feed, and the current revision. Login uses the same
cookie session as the OAuth consent pages.
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .auth.web import _page, COOKIE
from .errors import ForbiddenError
from .runtime import get_store

router = APIRouter(prefix="/console")


def _user(request: Request) -> str | None:
    return get_store().auth.get_login_user(request.cookies.get(COOKIE))


def _esc(v: object) -> str:
    return html.escape(str(v))


@router.get("", response_class=HTMLResponse)
def home(request: Request):
    store = get_store()
    uid = _user(request)
    if not uid:
        return RedirectResponse("/auth/login", status_code=303)
    project_ids = store.projects.list_user_project_ids(uid)
    items = []
    for pid in project_ids:
        p = store.projects.get_project(pid)
        if p:
            items.append(
                f'<li><a href="/console/projects/{p.id}">{_esc(p.name)}</a> '
                f'<span class="muted">r{p.context_revision}</span></li>'
            )
    body = (
        "<h1>Shared Agent Context</h1>"
        f"<h2>Your projects</h2><ul>{''.join(items) or '<li class=muted>None</li>'}</ul>"
        '<p><a href="/auth/connections">Connected clients</a></p>'
    )
    return HTMLResponse(_page("SAC Console", body))


def _memory_row(m, can_write: bool) -> str:
    action = ""
    if can_write and m.status == "active":
        action = (
            f'<form class="inline" method="post" '
            f'action="/console/projects/{m.project_id}/memories/{m.id}/retract">'
            f'<button class="secondary" type="submit">Retract</button></form>'
        )
    tags = f' <span class="muted">[{_esc(",".join(m.tags))}]</span>' if m.tags else ""
    return (
        f"<li><b>{_esc(m.kind)}</b> (r{m.revision}, {_esc(m.status)}) "
        f"{_esc(m.summary)}{tags} {action}</li>"
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(project_id: str, request: Request):
    store = get_store()
    uid = _user(request)
    if not uid:
        return RedirectResponse("/auth/login", status_code=303)
    role = store.projects.get_role(project_id, uid)
    if role is None:
        return HTMLResponse(_page("Forbidden", "<h1>Not permitted</h1>"), status_code=403)
    project = store.projects.get_project(project_id)
    can_write = role in ("owner", "admin", "member")

    members = store.projects.list_members(project_id)
    member_items = "".join(
        f'<li>{_esc(m["display_name"] or m["email"])} '
        f'<span class="muted">({_esc(m["role"])})</span></li>'
        for m in members
    )

    shared = store.memories.list_memories(project_id, uid, scope="shared", status=None, limit=200)
    private = store.memories.list_memories(project_id, uid, scope="private", status="active", limit=200)
    shared_items = "".join(_memory_row(m, can_write) for m in shared) or "<li class=muted>None</li>"
    private_items = "".join(_memory_row(m, can_write) for m in private) or "<li class=muted>None</li>"

    audit = store.audit.recent(project_id, limit=25)
    audit_items = "".join(
        f'<li class="muted">{_esc(a["created_at"])} · {_esc(a["action"])} '
        f'{_esc(a["entity_type"])}</li>'
        for a in audit
    ) or "<li class=muted>None</li>"

    body = f"""<h1>{_esc(project.name)}</h1>
<p class="muted">Revision r{project.context_revision} · your role: {_esc(role)}</p>
<h2>Members</h2><ul>{member_items}</ul>
<h2>Shared memory</h2><ul>{shared_items}</ul>
<h2>Your private memory</h2><ul>{private_items}</ul>
<h2>Recent activity</h2><ul>{audit_items}</ul>
<p><a href="/console">← All projects</a> · <a href="/auth/connections">Connected clients</a></p>"""
    return HTMLResponse(_page(project.name, body))


@router.post("/projects/{project_id}/memories/{memory_id}/retract")
def retract_memory(project_id: str, memory_id: str, request: Request):
    store = get_store()
    uid = _user(request)
    if not uid:
        return RedirectResponse("/auth/login", status_code=303)
    from .identity import Principal

    try:
        identity = store.resolve_identity(
            Principal(uid, None, ("sac.read", "sac.write")), project_id
        )
        store.memories.retract(identity, memory_id)
    except ForbiddenError:
        return HTMLResponse(_page("Forbidden", "<h1>Not permitted</h1>"), status_code=403)
    return RedirectResponse(f"/console/projects/{project_id}", status_code=303)
