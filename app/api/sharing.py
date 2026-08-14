"""Sharing a context with other people.

Access levels shown to users map onto the roles the engine already enforces:

    view   -> viewer   read shared memory, no writes
    edit   -> member   read + publish shared and own private memory
    manage -> admin    edit + share with others and change access
    (owner)            manage + archive/transfer

Only humans share. Agents never get a sharing tool — see
RESEARCH_CONTEXT_SHARING_AND_THIRD_PARTY_ACCESS_2026.md:550-575 and
PRIVACY_PERMISSION_ARCHITECTURE.md:199-206.
"""
from __future__ import annotations

from typing import Any

from .. import email as mailer
from ..errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..identity import RequestIdentity
from ..limits import MAX_MEMBERS_PER_CONTEXT, enforce_quota, require_verified
from ..models import (
    ACCESS_TO_ROLE,
    LINK_ACCESS_LEVELS,
    ROLE_TO_ACCESS,
    SHARER_ROLES,
)
from ..stores import SACStore


def _require_sharer(identity: RequestIdentity) -> None:
    if identity.role not in SHARER_ROLES:
        raise ForbiddenError("only owners and admins can share this context")


def _display_name(store: SACStore, user_id: str) -> str:
    user = store.projects.get_user(user_id)
    if not user:
        return "Someone"
    return user.get("display_name") or user.get("email") or "Someone"


def _role_for(access: str) -> str:
    role = ACCESS_TO_ROLE.get((access or "").strip().lower())
    if role is None:
        raise ValidationError("access must be one of: view, edit, manage")
    return role


def _owner_count(store: SACStore, project_id: str) -> int:
    return sum(
        1 for m in store.projects.list_members(project_id) if m["role"] == "owner"
    )


def share_context(
    store: SACStore,
    identity: RequestIdentity,
    email: str,
    access: str = "edit",
    base_url: str = "",
) -> dict[str, Any]:
    """Grant someone access by email.

    If they already have an account they are added immediately. If not, an
    invite is created and the caller is handed a link to send them.
    """
    _require_sharer(identity)
    # This gate used to be unreachable and is now load-bearing. Creating a
    # context no longer needs a verified address (api/impl.py:create_context),
    # so without it a throwaway account could make a context and use this path
    # to send invite mail — from Osmos, to any address it chose — which is the
    # whole apparatus of a spam relay.
    require_verified(store, identity.user_id, "share a context")
    email = (email or "").strip().lower()
    if not email:
        raise ValidationError("email is required")
    role = _role_for(access)

    enforce_quota(
        store,
        len(store.projects.list_members(identity.project_id)),
        MAX_MEMBERS_PER_CONTEXT,
        "members per context",
    )
    inviter = _display_name(store, identity.user_id)

    existing_user = store.projects.get_user_by_email(email)
    # An account that never proved it controls the mailbox does not count as
    # "this person already has an account". Otherwise anyone could register
    # victim@example.com, leave it unverified, and silently collect every
    # context later shared to that address. Falling through to the invite path
    # means only whoever can read the mail can redeem it.
    if existing_user and not store.auth.is_email_verified(existing_user["id"]):
        existing_user = None

    if existing_user:
        if existing_user["id"] == identity.user_id:
            raise ValidationError("you already have access to this context")
        store.projects.add_membership(identity.project_id, existing_user["id"], role=role)
        mailer.send_share_notice(email, identity.context_name, inviter, access)
        store.audit.emit(
            "context.share", "membership", existing_user["id"],
            project_id=identity.project_id, actor_user_id=identity.user_id,
            actor_agent_id=identity.agent_connection_id,
            meta={"email": email, "access": access, "role": role, "direct": True},
        )
        return {
            "ok": True,
            "shared": True,
            "invited": False,
            "email": email,
            "access": access,
            "message": f"{email} now has {access} access to '{identity.context_name}'.",
        }

    invite_id, code = store.invites.create(
        identity.project_id, role=role,
        created_by_user_id=identity.user_id, email=email,
    )
    mailer.send_invite(email, code, identity.context_name, inviter, access)
    store.audit.emit(
        "context.invite", "invite", invite_id,
        project_id=identity.project_id, actor_user_id=identity.user_id,
        actor_agent_id=identity.agent_connection_id,
        meta={"email": email, "access": access, "role": role},
    )
    link = f"{base_url.rstrip('/')}/invite/{code}" if base_url else f"/invite/{code}"
    return {
        "ok": True,
        "shared": False,
        "invited": True,
        "email": email,
        "access": access,
        "invite_id": invite_id,
        "invite_link": link,
        "message": f"Invite created for {email} ({access} access).",
    }


def accept_invite(store: SACStore, code: str, user_id: str) -> dict[str, Any]:
    """Redeem an invite for an existing (already signed-in) user.

    Redeeming an invite looks like it should prove control of the mailbox it was
    sent to, which would make the separate verification step redundant. It does
    not: ``share_context`` returns ``invite_link`` to the *sharer* as well, so
    the link can be delivered by hand when email is unavailable. Possession of a
    code therefore proves only that you are the invitee **or the person who
    issued it**.

    That distinction has teeth. Without it, anyone could invite
    victim@example.com, register that address themselves, redeem their own code,
    and end up holding a *verified* account for an address they never controlled
    — which the sharing path above then trusts. So the verification gate stays.
    """
    require_verified(store, user_id, "accept a shared context")
    invite = store.invites.get_by_code(code)
    if invite is None:
        raise NotFoundError("this invite is invalid, expired, or already used")

    # An invite addressed to a specific email may only be used by that account.
    user = store.projects.get_user(user_id)
    if invite["email"] and user and user["email"].lower() != invite["email"]:
        raise ForbiddenError("this invite was issued to a different email address")

    project_id = invite["project_id"]
    existing_role = store.projects.get_role(project_id, user_id)
    if existing_role is None:
        store.projects.add_membership(project_id, user_id, role=invite["role"])
    store.invites.redeem(invite["id"], user_id)
    store.audit.emit(
        "context.invite_accepted", "invite", invite["id"],
        project_id=project_id, actor_user_id=user_id,
        meta={"role": invite["role"]},
    )
    name = store.invites.get_project_name(project_id)
    return {
        "ok": True,
        "project_id": project_id,
        "context_name": name,
        "access": ROLE_TO_ACCESS.get(invite["role"], invite["role"]),
        "already_member": existing_role is not None,
    }


def change_access(
    store: SACStore, identity: RequestIdentity, user_id: str, access: str
) -> dict[str, Any]:
    """Change a member's access level, protecting the last owner."""
    _require_sharer(identity)
    role = _role_for(access)
    current = store.projects.get_role(identity.project_id, user_id)
    if current is None:
        raise NotFoundError("that person is not a member of this context")
    if current == "owner" and role != "owner" and _owner_count(store, identity.project_id) <= 1:
        raise ConflictError("a context must always have at least one owner")
    store.projects.add_membership(identity.project_id, user_id, role=role)
    store.audit.emit(
        "context.access_change", "membership", user_id,
        project_id=identity.project_id, actor_user_id=identity.user_id,
        meta={"from": current, "to": role},
    )
    return {"ok": True, "user_id": user_id, "access": access}


def revoke_access(
    store: SACStore, identity: RequestIdentity, user_id: str
) -> dict[str, Any]:
    """Remove someone from a context, protecting the last owner."""
    _require_sharer(identity)
    current = store.projects.get_role(identity.project_id, user_id)
    if current is None:
        raise NotFoundError("that person is not a member of this context")
    if current == "owner" and _owner_count(store, identity.project_id) <= 1:
        raise ConflictError("a context must always have at least one owner")
    store.projects.remove_membership(identity.project_id, user_id)
    # Don't leave their clients pointed at a context they can no longer read.
    store.projects.clear_bindings_for_user_project(user_id, identity.project_id)
    store.audit.emit(
        "context.access_revoked", "membership", user_id,
        project_id=identity.project_id, actor_user_id=identity.user_id,
        meta={"was": current},
    )
    return {"ok": True, "user_id": user_id, "revoked": True}


# --- "anyone with the link" -------------------------------------------------


def _link_payload(
    project, may_share: bool, base_url: str = ""
) -> dict[str, Any]:
    """Describe the link, revealing the token only to someone who may share it.

    Everyone in a context can see *that* it is link-shared — that is material to
    deciding what to write in it. Only owners and managers get the token,
    because holding the token is operationally the same as being able to share.
    """
    access = project.link_access or "none"
    token = project.link_token if (may_share and access != "none") else None
    url = f"{base_url.rstrip('/')}/c/{token}" if (token and base_url) else (
        f"/c/{token}" if token else ""
    )
    return {"access": access, "token": token, "url": url}


def get_link(
    store: SACStore, identity: RequestIdentity, base_url: str = ""
) -> dict[str, Any]:
    project = store.projects.get_project(identity.project_id)
    if project is None:
        raise NotFoundError("context not found")
    return _link_payload(project, identity.role in SHARER_ROLES, base_url)


def set_link_access(
    store: SACStore, identity: RequestIdentity, access: str, base_url: str = ""
) -> dict[str, Any]:
    """Open or close the context to anyone holding its link."""
    _require_sharer(identity)
    level = (access or "").strip().lower()
    if level not in LINK_ACCESS_LEVELS:
        raise ValidationError(
            "link access must be one of: none, view, edit — a link cannot grant "
            "manage, because that would let it share itself further"
        )
    store.projects.set_link_access(identity.project_id, level)
    store.audit.emit(
        "context.link_access", "project", identity.project_id,
        project_id=identity.project_id, actor_user_id=identity.user_id,
        meta={"access": level},
    )
    project = store.projects.get_project(identity.project_id)
    return {"ok": True, **_link_payload(project, True, base_url)}


def rotate_link(
    store: SACStore, identity: RequestIdentity, base_url: str = ""
) -> dict[str, Any]:
    """Replace the link, breaking every copy already circulating."""
    _require_sharer(identity)
    store.projects.rotate_link_token(identity.project_id)
    store.audit.emit(
        "context.link_rotate", "project", identity.project_id,
        project_id=identity.project_id, actor_user_id=identity.user_id,
    )
    project = store.projects.get_project(identity.project_id)
    return {"ok": True, **_link_payload(project, True, base_url)}


def join_by_link(store: SACStore, token: str, user_id: str) -> dict[str, Any]:
    """Redeem a share link.

    A closed link, a rotated-away token, an archived context, and a token that
    never existed all raise the same NotFoundError, so the endpoint cannot be
    used to discover which contexts exist.
    """
    project = store.projects.get_by_link_token((token or "").strip())
    if project is None:
        raise NotFoundError("this link is invalid or no longer active")

    require_verified(store, user_id, "join a shared context")
    existing_role = store.projects.get_role(project.id, user_id)
    if existing_role is not None:
        # Already in. Never re-grant: a view link must not demote an editor, and
        # must certainly not demote the owner.
        return {
            "ok": True,
            "project_id": project.id,
            "context_name": project.name,
            "access": ROLE_TO_ACCESS.get(existing_role, existing_role),
            "already_member": True,
        }

    enforce_quota(
        store,
        len(store.projects.list_members(project.id)),
        MAX_MEMBERS_PER_CONTEXT,
        "members per context",
    )
    role = ACCESS_TO_ROLE[project.link_access]
    store.projects.add_membership(project.id, user_id, role=role)
    store.audit.emit(
        "context.link_join", "membership", user_id,
        project_id=project.id, actor_user_id=user_id,
        meta={"access": project.link_access, "role": role},
    )
    return {
        "ok": True,
        "project_id": project.id,
        "context_name": project.name,
        "access": project.link_access,
        "already_member": False,
    }


def list_shares(
    store: SACStore, identity: RequestIdentity, base_url: str = ""
) -> dict[str, Any]:
    """Members, pending invites, and the link state for a context."""
    members = [
        {
            "user_id": m["user_id"],
            "email": m["email"],
            "display_name": m["display_name"],
            "role": m["role"],
            "access": ROLE_TO_ACCESS.get(m["role"], m["role"]),
        }
        for m in store.projects.list_members(identity.project_id)
    ]
    pending = [
        {
            "id": i["id"],
            "email": i["email"],
            "access": ROLE_TO_ACCESS.get(i["role"], i["role"]),
            "expires_at": i["expires_at"].isoformat() if i["expires_at"] else None,
        }
        for i in store.invites.list_pending(identity.project_id)
    ]
    # Organisation state, so the share dialog can show all three dials together:
    # named people, anyone with the link, and everyone in the owning group.
    project = store.projects.get_project(identity.project_id)
    org = {"id": None, "name": "", "access": "none"}
    if project is not None and project.org_id:
        record = store.orgs.get(project.org_id)
        org = {
            "id": project.org_id,
            "name": (record or {}).get("name", ""),
            "access": project.org_access or "none",
        }

    return {
        "ok": True,
        "members": members,
        "pending_invites": pending,
        "link": get_link(store, identity, base_url),
        "org": org,
        # Organisations the caller could move this context into: ones they
        # administer. Only meaningful to an owner, who is the only role allowed
        # to move a context.
        "your_orgs": (
            [
                {"id": o["id"], "name": o["name"]}
                for o in store.orgs.list_for_user(identity.user_id)
                if o["org_role"] in ("owner", "admin")
            ]
            if identity.role == "owner"
            else []
        ),
        "can_share": identity.role in SHARER_ROLES,
        "your_role": identity.role,
    }
