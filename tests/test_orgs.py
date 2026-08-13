"""Organisations above contexts.

The design being defended: organisation access is **materialised into
`memberships`** rather than checked as a parallel permission path, so
`_visible()` and `resolve_identity` never learn a second concept. Everything
below either verifies that materialisation is faithful, or verifies the two
properties that make it safe:

**Nothing is exposed by accident.** `org_access` defaults to `none`, so creating
an organisation and moving contexts into it changes nobody's access. Being an
organisation admin lets you see *that* a context exists, never what is in it.

**Direct outranks org.** An explicit invitation survives leaving the
organisation. Without that rule, one person removing another from a group would
silently revoke access a third person had granted individually.
"""
from __future__ import annotations

import pytest

from app.errors import ConflictError, ForbiddenError, ValidationError
from app.identity import Principal
from app.models import READ_SCOPE, WRITE_SCOPE


def _principal(user_id: str) -> Principal:
    return Principal(user_id, None, (READ_SCOPE, WRITE_SCOPE))


def _can_read(seed, user_id: str, project_id: str) -> bool:
    """Does this person actually reach the memory? The only question that counts."""
    from app.errors import SACError

    try:
        identity = seed.store.resolve_identity(_principal(user_id), project_id)
    except SACError:
        return False
    seed.store.memories.list_memories(project_id, user_id)
    return identity.role is not None


@pytest.fixture
def org(seed):
    """An organisation owned by Alice, with a context moved into it."""
    orgs = seed.store.orgs
    created = orgs.create("Acme Inc", seed.alice_user_id)
    orgs.attach_project(created["id"], seed.project_id)
    return created


# --- creating ---------------------------------------------------------------


def test_the_creator_becomes_the_owner(seed):
    created = seed.store.orgs.create("Acme Inc", seed.alice_user_id)
    assert created["org_role"] == "owner"
    assert seed.store.orgs.get_org_role(created["id"], seed.alice_user_id) == "owner"


def test_organisations_get_unique_slugs(seed):
    a = seed.store.orgs.create("Acme Inc", seed.alice_user_id)
    b = seed.store.orgs.create("Acme Inc", seed.bob_user_id)
    assert a["slug"] == "acme-inc"
    assert b["slug"] == "acme-inc-2"


def test_a_nameless_organisation_is_refused(seed):
    with pytest.raises(ValidationError):
        seed.store.orgs.create("   ", seed.alice_user_id)


def test_list_for_user_shows_only_their_organisations(seed):
    mine = seed.store.orgs.create("Mine", seed.alice_user_id)
    seed.store.orgs.create("Theirs", seed.carol.user_id)
    listed = seed.store.orgs.list_for_user(seed.alice_user_id)
    assert [o["id"] for o in listed] == [mine["id"]]
    assert listed[0]["member_count"] == 1


# --- moving a context in changes nothing on its own -------------------------


def test_attaching_a_context_does_not_change_anyones_access(seed, org):
    """Moving a context into an organisation must never expose its memory."""
    assert seed.store.orgs.get(org["id"]) is not None
    seed.store.orgs.add_member(org["id"], seed.carol.user_id)
    # Carol is in the organisation, but the context has granted nothing.
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is False


def test_org_access_defaults_to_none(seed, org):
    contexts = seed.store.orgs.list_org_contexts(org["id"])
    assert [c["org_access"] for c in contexts] == ["none"]


def test_setting_org_access_grants_every_member(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "view")
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is True
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "viewer"


def test_joining_later_picks_up_existing_org_access(seed, org):
    """Order must not matter: set access then join, or join then set access."""
    orgs = seed.store.orgs
    orgs.set_org_access(seed.project_id, "edit")
    orgs.add_member(org["id"], seed.carol.user_id)
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "member"


def test_org_access_cannot_grant_manage(seed, org):
    """The same rule as share links: access must not propagate itself."""
    with pytest.raises(ValidationError) as exc:
        seed.store.orgs.set_org_access(seed.project_id, "manage")
    assert "manage" in str(exc.value)


def test_org_access_on_a_personal_context_is_refused(seed):
    with pytest.raises(ValidationError):
        seed.store.orgs.set_org_access(seed.other_project_id, "view")


def test_lowering_org_access_downgrades_members(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "edit")
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "member"
    orgs.set_org_access(seed.project_id, "view")
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "viewer"


def test_setting_org_access_to_none_revokes_it(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "edit")
    orgs.set_org_access(seed.project_id, "none")
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is False


def test_a_viewer_by_org_access_cannot_write(seed, org):
    """The level is enforced by the engine, exactly as for any other member."""
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "view")
    identity = seed.store.resolve_identity(
        _principal(seed.carol.user_id), seed.project_id
    )
    with pytest.raises(ForbiddenError):
        seed.store.memories.remember(
            identity, scope="shared", kind="note", summary="not allowed"
        )


# --- direct outranks org ----------------------------------------------------


def test_an_explicit_invitation_survives_leaving_the_organisation(seed, org):
    """The rule that keeps one person's group change from revoking another
    person's individual grant."""
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "view")
    # Alice also invites Carol directly, as an editor.
    seed.store.projects.add_membership(
        seed.project_id, seed.carol.user_id, role="member"
    )

    orgs.remove_member(org["id"], seed.carol.user_id)
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "member"
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is True


def test_org_access_does_not_downgrade_an_explicit_role(seed, org):
    orgs = seed.store.orgs
    seed.store.projects.add_membership(
        seed.project_id, seed.carol.user_id, role="admin"
    )
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "view")
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "admin"


def test_leaving_the_organisation_revokes_org_derived_access(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "edit")
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is True
    orgs.remove_member(org["id"], seed.carol.user_id)
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is False


def test_existing_memberships_are_direct_by_default(seed):
    """Access granted before organisations existed came from a human."""
    from sqlalchemy import select

    from app.db import memberships

    with seed.store.engine.begin() as conn:
        sources = {
            r[0]
            for r in conn.execute(select(memberships.c.source)).all()
        }
    assert sources == {"direct"}


def test_detaching_a_context_revokes_org_access_but_not_invitations(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "edit")
    # Bob was a direct member from the start of the fixture.
    orgs.detach_project(seed.project_id)
    assert _can_read(seed, seed.carol.user_id, seed.project_id) is False
    assert seed.store.projects.get_role(seed.project_id, seed.bob_user_id) == "member"


# --- administering an organisation is not reading it ------------------------


def test_an_org_admin_without_access_cannot_read_a_context(seed, org):
    """The property that makes an org layer safe to add at all.

    Dan administers the organisation. The context belongs to it. He can see the
    context exists — that is what administering a group requires — and he cannot
    read one word of its memory.
    """
    orgs = seed.store.orgs
    dan = seed.store.projects.create_user("dan@example.com", "Dan")
    orgs.add_member(org["id"], dan, org_role="admin")
    seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Commercially sensitive."
    )

    listed = orgs.list_org_contexts(org["id"])
    assert [c["name"] for c in listed] == ["Shared Desktop App"]
    # Metadata only — no memory in the payload.
    assert not any("Commercially sensitive." in str(c) for c in listed)
    assert _can_read(seed, dan, seed.project_id) is False


def test_an_org_admin_cannot_reach_memory_through_the_store(seed, org):
    orgs = seed.store.orgs
    dan = seed.store.projects.create_user("dan@example.com", "Dan")
    orgs.add_member(org["id"], dan, org_role="admin")
    with pytest.raises(ForbiddenError):
        seed.store.resolve_identity(_principal(dan), seed.project_id)


def test_org_membership_does_not_leak_across_organisations(seed):
    orgs = seed.store.orgs
    mine = orgs.create("Mine", seed.alice_user_id)
    theirs = orgs.create("Theirs", seed.carol.user_id)
    orgs.attach_project(theirs["id"], seed.other_project_id)
    orgs.set_org_access(seed.other_project_id, "edit")
    # Alice is in her own organisation only.
    assert _can_read(seed, seed.alice_user_id, seed.other_project_id) is False
    assert orgs.list_org_contexts(mine["id"]) == []


def test_a_plain_member_cannot_administer(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id, org_role="member")
    with pytest.raises(ForbiddenError):
        orgs.require_org_admin(org["id"], seed.carol.user_id)


def test_a_non_member_gets_the_same_answer_as_a_missing_organisation(seed, org):
    """No existence oracle for organisations either."""
    with pytest.raises(ForbiddenError) as outsider:
        seed.store.orgs.require_org_admin(org["id"], seed.carol.user_id)
    with pytest.raises(ForbiddenError) as absent:
        seed.store.orgs.require_org_admin("no-such-org", seed.carol.user_id)
    assert str(outsider.value) == str(absent.value)


def test_an_organisation_keeps_at_least_one_owner(seed, org):
    with pytest.raises(ConflictError):
        seed.store.orgs.remove_member(org["id"], seed.alice_user_id)


def test_an_invalid_org_role_is_refused(seed, org):
    with pytest.raises(ValidationError):
        seed.store.orgs.add_member(org["id"], seed.carol.user_id, org_role="superuser")


# --- the context surfaces keep working -------------------------------------


def test_org_derived_access_appears_in_the_normal_context_list(seed, org):
    """An org-derived member should be indistinguishable from an invited one."""
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "view")
    names = [
        c["name"] for c in seed.store.projects.list_user_contexts(seed.carol.user_id)
    ]
    assert "Shared Desktop App" in names


def test_org_derived_access_resolves_by_name(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "edit")
    resolved = seed.store.projects.resolve_context_ref(
        seed.carol.user_id, "Shared Desktop App"
    )
    assert resolved == seed.project_id


def test_member_count_includes_org_derived_members(seed, org):
    orgs = seed.store.orgs
    orgs.add_member(org["id"], seed.carol.user_id)
    orgs.set_org_access(seed.project_id, "view")
    contexts = seed.store.projects.list_user_contexts(seed.alice_user_id)
    assert contexts[0]["member_count"] == 3  # alice, bob, carol


# --- the HTTP surface -------------------------------------------------------


@pytest.fixture
def api(wired, monkeypatch):
    from fastapi.testclient import TestClient

    from app.browser import CSRF_COOKIE, CSRF_HEADER
    from app.main import app as real_app

    seed = wired
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    for uid in (seed.alice_user_id, seed.bob_user_id, seed.carol.user_id):
        seed.store.auth.set_password(uid, "correct-horse-battery")

    client = TestClient(real_app, follow_redirects=False)

    def sign_in(email="alice@example.com"):
        client.cookies.clear()
        r = client.post(
            "/auth/login", data={"email": email, "password": "correct-horse-battery"}
        )
        assert r.status_code == 303
        client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]

    sign_in()
    return client, seed, sign_in


def test_create_and_read_an_organisation(api):
    c, seed, _ = api
    created = c.post("/v1/orgs", json={"name": "Acme Inc"})
    assert created.status_code == 200, created.text
    org_id = created.json()["org"]["id"]

    listed = c.get("/v1/orgs").json()["orgs"]
    assert [o["name"] for o in listed] == ["Acme Inc"]

    detail = c.get(f"/v1/orgs/{org_id}").json()
    assert detail["your_role"] == "owner"
    assert [m["email"] for m in detail["members"]] == ["alice@example.com"]
    assert detail["contexts"] == []


def test_a_non_member_cannot_read_an_organisation(api):
    c, seed, sign_in = api
    org_id = c.post("/v1/orgs", json={"name": "Acme Inc"}).json()["org"]["id"]
    sign_in("carol@example.com")
    assert c.get(f"/v1/orgs/{org_id}").status_code == 403


def test_moving_a_context_in_and_granting_access(api):
    c, seed, sign_in = api
    org_id = c.post("/v1/orgs", json={"name": "Acme Inc"}).json()["org"]["id"]
    c.post(
        f"/v1/orgs/{org_id}/members",
        json={"email": "carol@example.com", "org_role": "member"},
    )

    moved = c.put(f"/v1/contexts/{seed.project_id}/org", json={"org_id": org_id})
    assert moved.status_code == 200, moved.text

    # Still nobody new can read it.
    sign_in("carol@example.com")
    assert c.get(f"/v1/projects/{seed.project_id}").status_code == 403

    sign_in()
    granted = c.put(
        f"/v1/contexts/{seed.project_id}/org-access", json={"access": "view"}
    )
    assert granted.status_code == 200, granted.text

    sign_in("carol@example.com")
    assert c.get(f"/v1/projects/{seed.project_id}").status_code == 200


def test_org_access_of_manage_is_refused_by_the_schema(api):
    c, seed, _ = api
    org_id = c.post("/v1/orgs", json={"name": "Acme"}).json()["org"]["id"]
    c.put(f"/v1/contexts/{seed.project_id}/org", json={"org_id": org_id})
    r = c.put(f"/v1/contexts/{seed.project_id}/org-access", json={"access": "manage"})
    assert r.status_code == 422


def test_only_the_context_owner_can_move_it(api):
    c, seed, sign_in = api
    org_id = c.post("/v1/orgs", json={"name": "Acme"}).json()["org"]["id"]
    c.post(
        f"/v1/orgs/{org_id}/members",
        json={"email": "bob@example.com", "org_role": "admin"},
    )
    sign_in("bob@example.com")  # an editor on the context, admin of the org
    r = c.put(f"/v1/contexts/{seed.project_id}/org", json={"org_id": org_id})
    assert r.status_code == 403


def test_moving_a_context_needs_admin_of_the_destination(api):
    """Both sides consent: you cannot push your context into someone's group."""
    c, seed, sign_in = api
    sign_in("carol@example.com")
    theirs = c.post("/v1/orgs", json={"name": "Theirs"}).json()["org"]["id"]
    sign_in()
    r = c.put(f"/v1/contexts/{seed.project_id}/org", json={"org_id": theirs})
    assert r.status_code == 403


def test_adding_an_unverified_account_to_an_organisation_is_refused(api):
    """Same reasoning as sharing: nobody has proved they hold that mailbox."""
    c, seed, _ = api
    seed.store.projects.create_user("squatter@example.com", "S")
    org_id = c.post("/v1/orgs", json={"name": "Acme"}).json()["org"]["id"]
    r = c.post(
        f"/v1/orgs/{org_id}/members", json={"email": "squatter@example.com"}
    )
    assert r.status_code == 404


def test_a_plain_org_member_cannot_add_people(api):
    c, seed, sign_in = api
    org_id = c.post("/v1/orgs", json={"name": "Acme"}).json()["org"]["id"]
    c.post(
        f"/v1/orgs/{org_id}/members",
        json={"email": "carol@example.com", "org_role": "member"},
    )
    sign_in("carol@example.com")
    r = c.post(f"/v1/orgs/{org_id}/members", json={"email": "bob@example.com"})
    assert r.status_code == 403


def test_removing_a_member_revokes_their_org_access(api):
    c, seed, sign_in = api
    org_id = c.post("/v1/orgs", json={"name": "Acme"}).json()["org"]["id"]
    c.post(f"/v1/orgs/{org_id}/members", json={"email": "carol@example.com"})
    c.put(f"/v1/contexts/{seed.project_id}/org", json={"org_id": org_id})
    c.put(f"/v1/contexts/{seed.project_id}/org-access", json={"access": "edit"})

    sign_in("carol@example.com")
    assert c.get(f"/v1/projects/{seed.project_id}").status_code == 200

    sign_in()
    removed = c.delete(f"/v1/orgs/{org_id}/members/{seed.carol.user_id}")
    assert removed.status_code == 200, removed.text

    sign_in("carol@example.com")
    assert c.get(f"/v1/projects/{seed.project_id}").status_code == 403


def test_the_org_endpoints_require_csrf(api):
    c, seed, _ = api
    from app.browser import CSRF_HEADER

    del c.headers[CSRF_HEADER]
    r = c.post("/v1/orgs", json={"name": "Sneaky"})
    assert r.status_code == 403 and r.json()["detail"] == "csrf_required"


def test_an_unverified_user_cannot_create_an_organisation(api, monkeypatch):
    c, seed, sign_in = api
    # Undo the seed's verification for carol only.
    from sqlalchemy import update

    from app.db import users

    with seed.store.engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed.carol.user_id)
            .values(email_verified_at=None)
        )
    sign_in("carol@example.com")
    r = c.post("/v1/orgs", json={"name": "Spam Inc"})
    assert r.status_code == 403
