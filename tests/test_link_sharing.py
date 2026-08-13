"""Link sharing — the "anyone with the link" dial, Google-Docs style.

A context now has two independent sharing controls:

  * **link access** — ``none`` (invited people only), ``view``, or ``edit``
  * **per-person role** — viewer / member / admin / owner

The important invariant is that these dials are not interchangeable. A link can
only ever hand out *view* or *edit*. It can never hand out *manage*, because
manage carries the right to re-share, and a link that multiplies itself is not a
permission a human ever knowingly granted. "Who can share this" therefore stays
a decision made per person, by a named owner or manager.
"""
from __future__ import annotations

import pytest

from app.api import sharing
from app.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError

# --- setting link access ----------------------------------------------------


def test_contexts_start_restricted(seed):
    link = sharing.get_link(seed.store, seed.alice)
    assert link["access"] == "none"
    assert link["token"] is None
    assert link["url"] == ""


def test_owner_can_open_a_view_link(seed):
    out = sharing.set_link_access(seed.store, seed.alice, "view", base_url="https://sac.test")
    assert out["access"] == "view"
    assert out["token"]
    assert out["url"] == f"https://sac.test/c/{out['token']}"


def test_opening_a_link_is_recorded_in_the_audit_trail(seed):
    sharing.set_link_access(seed.store, seed.alice, "edit")
    kinds = [e["action"] for e in seed.store.audit.recent(seed.project_id)]
    assert "context.link_access" in kinds


def test_link_token_is_long_enough_to_be_unguessable(seed):
    out = sharing.set_link_access(seed.store, seed.alice, "view")
    assert len(out["token"]) >= 32


def test_reopening_a_link_keeps_the_same_token(seed):
    """Flipping view -> edit must not silently break links already handed out."""
    first = sharing.set_link_access(seed.store, seed.alice, "view")
    second = sharing.set_link_access(seed.store, seed.alice, "edit")
    assert second["token"] == first["token"]
    assert second["access"] == "edit"


def test_closing_a_link_keeps_the_token_for_later(seed):
    opened = sharing.set_link_access(seed.store, seed.alice, "view")
    closed = sharing.set_link_access(seed.store, seed.alice, "none")
    assert closed["access"] == "none"
    # The URL is withheld while closed, but reopening restores the same link.
    assert closed["url"] == ""
    again = sharing.set_link_access(seed.store, seed.alice, "view")
    assert again["token"] == opened["token"]


# --- a link can never confer the right to re-share ---------------------------


def test_link_access_cannot_be_manage(seed):
    with pytest.raises(ValidationError) as exc:
        sharing.set_link_access(seed.store, seed.alice, "manage")
    assert "view" in str(exc.value) and "edit" in str(exc.value)


def test_link_access_rejects_arbitrary_values(seed):
    for bad in ("owner", "admin", "", "manage", "read", "write"):
        with pytest.raises(ValidationError):
            sharing.set_link_access(seed.store, seed.alice, bad)


def test_joining_by_link_never_grants_a_sharer_role(seed):
    """The joiner must not be able to turn around and share the context."""
    sharing.set_link_access(seed.store, seed.alice, "edit")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.join_by_link(seed.store, token, seed.carol.user_id)

    carol_here = seed.store.resolve_identity(
        _carol_principal(seed), seed.project_id
    )
    assert carol_here.role == "member"
    with pytest.raises(ForbiddenError):
        sharing.set_link_access(seed.store, carol_here, "view")
    with pytest.raises(ForbiddenError):
        sharing.share_context(seed.store, carol_here, "stranger@example.com", "view")


def _carol_principal(seed):
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    return Principal(seed.carol.user_id, None, (READ_SCOPE, WRITE_SCOPE))


# --- only owners and managers may touch the link ----------------------------


def test_a_member_cannot_open_a_link(seed):
    """Editors can write memory; they cannot widen who else can read it."""
    with pytest.raises(ForbiddenError):
        sharing.set_link_access(seed.store, seed.bob, "view")


def test_a_member_cannot_read_the_link_token(seed):
    """Knowing the token is equivalent to being able to share it."""
    sharing.set_link_access(seed.store, seed.alice, "view")
    link = sharing.get_link(seed.store, seed.bob)
    assert link["access"] == "view"  # they may know the context is link-shared
    assert link["token"] is None  # but not be able to hand the link out
    assert link["url"] == ""


def test_a_manager_can_open_a_link(seed):
    seed.store.projects.add_membership(seed.project_id, seed.bob_user_id, role="admin")
    bob_admin = seed.store.resolve_identity(
        _principal_for(seed, seed.bob_user_id, seed.bob_conn), seed.project_id
    )
    out = sharing.set_link_access(seed.store, bob_admin, "view")
    assert out["access"] == "view"


def _principal_for(seed, user_id, conn_id):
    from app.identity import Principal
    from app.models import READ_SCOPE, WRITE_SCOPE

    return Principal(user_id, conn_id, (READ_SCOPE, WRITE_SCOPE))


# --- joining ----------------------------------------------------------------


def test_join_by_link_grants_the_link_level(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    out = sharing.join_by_link(seed.store, token, seed.carol.user_id)
    assert out["access"] == "view"
    assert out["project_id"] == seed.project_id
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "viewer"


def test_a_viewer_who_joined_by_link_cannot_write(seed):
    """The level is enforced by the engine, not by the joining flow."""
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.join_by_link(seed.store, token, seed.carol.user_id)
    carol_here = seed.store.resolve_identity(_carol_principal(seed), seed.project_id)
    with pytest.raises(ForbiddenError):
        seed.store.memories.remember(
            carol_here, scope="shared", kind="decision", summary="Not allowed."
        )


def test_join_is_refused_when_the_link_is_closed(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.set_link_access(seed.store, seed.alice, "none")
    with pytest.raises(NotFoundError):
        sharing.join_by_link(seed.store, token, seed.carol.user_id)
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) is None


def test_closing_a_link_does_not_remove_existing_members(seed):
    sharing.set_link_access(seed.store, seed.alice, "edit")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.join_by_link(seed.store, token, seed.carol.user_id)
    sharing.set_link_access(seed.store, seed.alice, "none")
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "member"


def test_rotating_the_link_invalidates_the_old_one(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    old = sharing.get_link(seed.store, seed.alice)["token"]
    new = sharing.rotate_link(seed.store, seed.alice)["token"]
    assert new != old
    with pytest.raises(NotFoundError):
        sharing.join_by_link(seed.store, old, seed.carol.user_id)
    # The replacement works.
    assert sharing.join_by_link(seed.store, new, seed.carol.user_id)["ok"] is True


def test_only_a_sharer_can_rotate(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    with pytest.raises(ForbiddenError):
        sharing.rotate_link(seed.store, seed.bob)


def test_an_unknown_token_is_a_flat_not_found(seed):
    """No oracle: an invalid token and a closed link look identical."""
    with pytest.raises(NotFoundError):
        sharing.join_by_link(seed.store, "totally-made-up-token", seed.carol.user_id)


def test_an_archived_context_refuses_link_joins(seed):
    sharing.set_link_access(seed.store, seed.alice, "edit")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    seed.store.projects.archive_project(seed.project_id)
    with pytest.raises(NotFoundError):
        sharing.join_by_link(seed.store, token, seed.carol.user_id)


def test_joining_twice_is_harmless(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.join_by_link(seed.store, token, seed.carol.user_id)
    out = sharing.join_by_link(seed.store, token, seed.carol.user_id)
    assert out["already_member"] is True


def test_a_link_never_downgrades_an_existing_member(seed):
    """Bob is already an editor; opening a view link must not demote him."""
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    out = sharing.join_by_link(seed.store, token, seed.bob_user_id)
    assert out["already_member"] is True
    assert seed.store.projects.get_role(seed.project_id, seed.bob_user_id) == "member"


def test_the_owner_joining_their_own_link_is_harmless(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.join_by_link(seed.store, token, seed.alice_user_id)
    assert seed.store.projects.get_role(seed.project_id, seed.alice_user_id) == "owner"


def test_link_join_is_audited(seed):
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    sharing.join_by_link(seed.store, token, seed.carol.user_id)
    events = seed.store.audit.recent(seed.project_id)
    joined = [e for e in events if e["action"] == "context.link_join"]
    assert joined and joined[0]["actor_user_id"] == seed.carol.user_id


def test_unverified_users_cannot_join_by_link(seed, monkeypatch):
    monkeypatch.setenv("SAC_REQUIRE_VERIFIED_EMAIL", "1")
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    dave = seed.store.projects.create_user("dave@example.com", "Dave")
    with pytest.raises(ForbiddenError) as exc:
        sharing.join_by_link(seed.store, token, dave)
    assert "verify" in str(exc.value).lower()


def test_link_join_respects_the_member_quota(seed, monkeypatch):
    monkeypatch.setattr(sharing, "MAX_MEMBERS_PER_CONTEXT", 2)
    sharing.set_link_access(seed.store, seed.alice, "view")
    token = sharing.get_link(seed.store, seed.alice)["token"]
    # alice + bob already fill the quota
    with pytest.raises(ConflictError):
        sharing.join_by_link(seed.store, token, seed.carol.user_id)


# --- the two dials stay independent -----------------------------------------


def test_link_access_does_not_change_per_person_roles(seed):
    sharing.set_link_access(seed.store, seed.alice, "edit")
    roles = {m["user_id"]: m["role"] for m in seed.store.projects.list_members(seed.project_id)}
    assert roles[seed.alice_user_id] == "owner"
    assert roles[seed.bob_user_id] == "member"


def test_list_shares_reports_the_link_state(seed):
    sharing.set_link_access(seed.store, seed.alice, "view", base_url="https://sac.test")
    out = sharing.list_shares(seed.store, seed.alice, base_url="https://sac.test")
    assert out["link"]["access"] == "view"
    assert out["link"]["url"].startswith("https://sac.test/c/")


def test_list_shares_withholds_the_link_from_a_non_sharer(seed):
    sharing.set_link_access(seed.store, seed.alice, "view", base_url="https://sac.test")
    out = sharing.list_shares(seed.store, seed.bob)
    assert out["link"]["access"] == "view"
    assert out["link"]["url"] == ""


# --- the HTTP surface -------------------------------------------------------


@pytest.fixture
def web(wired, monkeypatch):
    """The real app, so cookie auth goes through the actual /v1 middleware.

    A hand-assembled router-only app would skip that middleware entirely and
    quietly test nothing — the whole point here is that a browser session
    reaches these endpoints.
    """
    from fastapi.testclient import TestClient

    from app.main import app as real_app

    seed = wired
    monkeypatch.setenv("SAC_PUBLIC_URL", "https://sac.test")
    for uid in (seed.alice_user_id, seed.carol.user_id):
        seed.store.auth.set_password(uid, "correct-horse-battery")
    return TestClient(real_app, follow_redirects=False), seed


def _login(client, email="alice@example.com"):
    """Sign in and start echoing the CSRF token, exactly as the front end does."""
    from app.browser import CSRF_COOKIE, CSRF_HEADER

    r = client.post(
        "/auth/login", data={"email": email, "password": "correct-horse-battery"}
    )
    assert r.status_code == 303
    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]


def test_rest_open_and_read_the_link(web):
    c, seed = web
    _login(c)
    r = c.put(f"/v1/contexts/{seed.project_id}/link", json={"access": "edit"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["url"] == f"https://sac.test/c/{token}"

    r = c.get(f"/v1/contexts/{seed.project_id}/link")
    assert r.json()["access"] == "edit" and r.json()["token"] == token


def test_rest_rejects_manage_as_a_link_level(web):
    """Caught by the schema, so it never reaches the sharing logic."""
    c, seed = web
    _login(c)
    r = c.put(f"/v1/contexts/{seed.project_id}/link", json={"access": "manage"})
    assert r.status_code == 422


def test_rest_rotate_changes_the_token(web):
    c, seed = web
    _login(c)
    old = c.put(
        f"/v1/contexts/{seed.project_id}/link", json={"access": "view"}
    ).json()["token"]
    new = c.post(f"/v1/contexts/{seed.project_id}/link/rotate").json()["token"]
    assert new != old


def test_link_page_shows_the_context_before_asking_to_sign_in(web):
    c, seed = web
    _login(c)
    token = c.put(
        f"/v1/contexts/{seed.project_id}/link", json={"access": "view"}
    ).json()["token"]
    c.cookies.clear()

    r = c.get(f"/c/{token}")
    assert r.status_code == 200
    assert "Shared Desktop App" in r.text
    assert "Create account" in r.text and "Sign in" in r.text
    # Deciding whether to join must not require reading the context first.
    assert "view" in r.text


def test_link_page_404s_on_a_bad_token(web):
    c, _ = web
    r = c.get("/c/not-a-real-token")
    assert r.status_code == 404


def test_joining_through_the_page_grants_access(web):
    c, seed = web
    _login(c)
    token = c.put(
        f"/v1/contexts/{seed.project_id}/link", json={"access": "view"}
    ).json()["token"]

    c.cookies.clear()
    _login(c, "carol@example.com")
    r = c.post(f"/c/{token}/join")
    assert r.status_code == 303
    assert r.headers["location"] == f"/console/c/{seed.project_id}?joined=1"
    assert seed.store.projects.get_role(seed.project_id, seed.carol.user_id) == "viewer"


def test_an_anonymous_join_is_sent_to_sign_in_and_back(web):
    c, seed = web
    _login(c)
    token = c.put(
        f"/v1/contexts/{seed.project_id}/link", json={"access": "view"}
    ).json()["token"]
    c.cookies.clear()
    r = c.post(f"/c/{token}/join")
    assert r.status_code == 303
    assert r.headers["location"] == f"/auth/login?next=/c/{token}"


def test_an_existing_member_opening_the_link_lands_in_the_context(web):
    c, seed = web
    _login(c)
    token = c.put(
        f"/v1/contexts/{seed.project_id}/link", json={"access": "view"}
    ).json()["token"]
    r = c.get(f"/c/{token}")
    assert r.status_code == 303
    assert r.headers["location"] == f"/console/c/{seed.project_id}"
