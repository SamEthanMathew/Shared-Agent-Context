"""Sharing a context by email: access levels, invites, and enforcement."""
from __future__ import annotations

import pytest

from app.api import sharing
from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.identity import Principal
from app.models import READ_SCOPE, WRITE_SCOPE


def _identity(seed, user_id, conn_id, project_id=None):
    return seed.store.resolve_identity(
        Principal(user_id, conn_id, (READ_SCOPE, WRITE_SCOPE)),
        project_id or seed.project_id,
    )


# --- sharing with an existing account ---------------------------------------


def test_share_with_existing_user_grants_immediately(seed):
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    out = sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="carol@example.com", access="view",
    )
    assert out["shared"] is True and out["invited"] is False
    assert seed.store.projects.get_role(seed.project_id, carol["id"]) == "viewer"


def test_shared_user_sees_context_in_their_list(seed):
    sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="carol@example.com", access="edit",
    )
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    names = {c["name"] for c in seed.store.projects.list_user_contexts(carol["id"])}
    assert "Shared Desktop App" in names


def test_access_levels_map_to_roles(seed):
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    for access, role in [("view", "viewer"), ("edit", "member"), ("manage", "admin")]:
        sharing.share_context(seed.store, ident, email="carol@example.com", access=access)
        assert seed.store.projects.get_role(seed.project_id, carol["id"]) == role


def test_invalid_access_rejected(seed):
    with pytest.raises(ValidationError):
        sharing.share_context(
            seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
            email="carol@example.com", access="superuser",
        )


# --- permission to share -----------------------------------------------------


def test_member_cannot_share(seed):
    # bob is a plain member (edit)
    with pytest.raises(ForbiddenError):
        sharing.share_context(
            seed.store, _identity(seed, seed.bob_user_id, seed.bob_conn),
            email="carol@example.com", access="view",
        )


def test_admin_can_share(seed):
    seed.store.projects.add_membership(seed.project_id, seed.bob_user_id, role="admin")
    out = sharing.share_context(
        seed.store, _identity(seed, seed.bob_user_id, seed.bob_conn),
        email="carol@example.com", access="view",
    )
    assert out["ok"] is True


# --- inviting someone with no account ---------------------------------------


def test_share_with_unknown_email_creates_invite(seed):
    out = sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="newcomer@example.com", access="edit",
        base_url="https://sac.example.com",
    )
    assert out["invited"] is True and out["shared"] is False
    assert out["invite_link"].startswith("https://sac.example.com/invite/")


def test_accept_invite_grants_access(seed):
    out = sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="newcomer@example.com", access="edit",
    )
    code = out["invite_link"].rsplit("/", 1)[1]
    newcomer = seed.store.projects.create_user("newcomer@example.com", "New")
    result = sharing.accept_invite(seed.store, code, newcomer)
    assert result["ok"] is True
    assert result["access"] == "edit"
    assert seed.store.projects.get_role(seed.project_id, newcomer) == "member"


def test_invite_is_single_use(seed):
    out = sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="newcomer@example.com", access="view",
    )
    code = out["invite_link"].rsplit("/", 1)[1]
    newcomer = seed.store.projects.create_user("newcomer@example.com", "New")
    sharing.accept_invite(seed.store, code, newcomer)
    other = seed.store.projects.create_user("other@example.com", "Other")
    with pytest.raises(NotFoundError):
        sharing.accept_invite(seed.store, code, other)


def test_invite_bound_to_its_email(seed):
    out = sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="intended@example.com", access="edit",
    )
    code = out["invite_link"].rsplit("/", 1)[1]
    interloper = seed.store.projects.create_user("interloper@example.com", "X")
    with pytest.raises(ForbiddenError):
        sharing.accept_invite(seed.store, code, interloper)


def test_revoked_invite_cannot_be_accepted(seed):
    out = sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="newcomer@example.com", access="edit",
    )
    code = out["invite_link"].rsplit("/", 1)[1]
    seed.store.invites.revoke(out["invite_id"])
    newcomer = seed.store.projects.create_user("newcomer@example.com", "New")
    with pytest.raises(NotFoundError):
        sharing.accept_invite(seed.store, code, newcomer)


def test_bad_code_rejected(seed):
    newcomer = seed.store.projects.create_user("newcomer@example.com", "New")
    with pytest.raises(NotFoundError):
        sharing.accept_invite(seed.store, "not-a-real-code", newcomer)


# --- access enforcement is server-side, not prompt-side ----------------------


def test_view_access_cannot_write(seed):
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="carol@example.com", access="view",
    )
    viewer = _identity(seed, carol["id"], None)
    with pytest.raises(ForbiddenError):
        seed.store.memories.remember(
            viewer, scope="shared", kind="note", summary="should be refused"
        )


def test_view_access_can_read(seed):
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    seed.store.memories.remember(
        _identity(seed, seed.alice_user_id, seed.alice_conn),
        scope="shared", kind="decision", summary="Visible to viewers.",
    )
    sharing.share_context(
        seed.store, _identity(seed, seed.alice_user_id, seed.alice_conn),
        email="carol@example.com", access="view",
    )
    mems = seed.store.memories.compile_candidates(seed.project_id, carol["id"])
    assert any("Visible to viewers." == m.summary for m in mems)


# --- changing and revoking access -------------------------------------------


def test_change_access_level(seed):
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    sharing.change_access(seed.store, ident, seed.bob_user_id, "view")
    assert seed.store.projects.get_role(seed.project_id, seed.bob_user_id) == "viewer"


def test_cannot_demote_last_owner(seed):
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    with pytest.raises(ConflictError):
        sharing.change_access(seed.store, ident, seed.alice_user_id, "view")


def test_cannot_revoke_last_owner(seed):
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    with pytest.raises(ConflictError):
        sharing.revoke_access(seed.store, ident, seed.alice_user_id)


def test_revoke_removes_access_and_binding(seed):
    ps = seed.store.projects
    ps.set_binding(seed.bob_user_id, seed.project_id, seed.bob_conn)
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    sharing.revoke_access(seed.store, ident, seed.bob_user_id)
    assert ps.get_role(seed.project_id, seed.bob_user_id) is None
    assert ps.get_binding(seed.bob_user_id, seed.bob_conn) is None
    # and the context disappears from their list
    assert ps.list_user_contexts(seed.bob_user_id) == []


def test_list_shares_reports_members_and_pending(seed):
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    sharing.share_context(seed.store, ident, email="pending@example.com", access="view")
    out = sharing.list_shares(seed.store, ident)
    accesses = {m["email"]: m["access"] for m in out["members"]}
    assert accesses["alice@example.com"] == "owner"
    assert accesses["bob@example.com"] == "edit"
    assert [i["email"] for i in out["pending_invites"]] == ["pending@example.com"]


def test_sharing_emits_audit_events(seed):
    ident = _identity(seed, seed.alice_user_id, seed.alice_conn)
    sharing.share_context(seed.store, ident, email="carol@example.com", access="view")
    actions = {a["action"] for a in seed.store.audit.recent(seed.project_id)}
    assert "context.share" in actions
