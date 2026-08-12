"""ProjectStore: users, projects, memberships, connections, revision, identity."""
from __future__ import annotations

import pytest

from app.errors import ForbiddenError, NotFoundError, ValidationError
from app.identity import Principal


def test_seed_shapes(seed):
    assert seed.alice.role == "owner"
    assert seed.bob.role == "member"
    assert seed.alice.project_id == seed.project_id
    assert seed.carol.project_id == seed.other_project_id


def test_project_starts_at_revision_zero(seed):
    assert seed.store.current_revision(seed.project_id) == 0


def test_revision_is_per_project_and_monotonic(seed):
    ps = seed.store.projects
    with seed.store.engine.begin() as conn:
        r1 = ps.next_revision(conn, seed.project_id)
        r2 = ps.next_revision(conn, seed.project_id)
    assert (r1, r2) == (1, 2)
    # the other project is untouched
    assert seed.store.current_revision(seed.other_project_id) == 0
    assert seed.store.current_revision(seed.project_id) == 2


def test_next_revision_missing_project(seed):
    with pytest.raises(NotFoundError):
        with seed.store.engine.begin() as conn:
            seed.store.projects.next_revision(conn, "no-such-project")


def test_non_member_cannot_resolve_identity(seed):
    # carol is not a member of alice+bob's project
    carol_user = seed.store.projects.get_user_by_email("carol@example.com")
    principal = Principal(user_id=carol_user["id"], agent_connection_id=None)
    with pytest.raises(ForbiddenError):
        seed.store.resolve_identity(principal, seed.project_id)


def test_add_membership_upserts_role(seed):
    ps = seed.store.projects
    ps.add_membership(seed.project_id, seed.bob_user_id, role="admin")
    assert ps.get_role(seed.project_id, seed.bob_user_id) == "admin"


def test_add_membership_rejects_bad_role(seed):
    with pytest.raises(ValidationError):
        seed.store.projects.add_membership(seed.project_id, seed.bob_user_id, role="wizard")


def test_list_members(seed):
    members = seed.store.projects.list_members(seed.project_id)
    emails = {m["email"] for m in members}
    assert emails == {"alice@example.com", "bob@example.com"}


def test_revoke_agent_connection(seed):
    ps = seed.store.projects
    ps.revoke_agent_connection(seed.bob_conn)
    row = ps.get_agent_connection(seed.bob_conn)
    assert row["revoked_at"] is not None


def test_create_project_requires_existing_owner(seed):
    with pytest.raises(NotFoundError):
        seed.store.projects.create_project("Orphan", owner_user_id="ghost")


def test_create_user_requires_email(seed):
    with pytest.raises(ValidationError):
        seed.store.projects.create_user("")
