"""Multi-context: slugs, listing, name resolution, bindings, precedence."""
from __future__ import annotations

import pytest

from app.api.deps import resolve_context, resolve_identity
from app.errors import ForbiddenError, NeedsContextSelection, ValidationError
from app.identity import Principal
from app.models import READ_SCOPE, WRITE_SCOPE
from app.stores.projects import slugify


def _principal(seed, which="alice"):
    if which == "alice":
        return Principal(seed.alice_user_id, seed.alice_conn, (READ_SCOPE, WRITE_SCOPE))
    return Principal(seed.bob_user_id, seed.bob_conn, (READ_SCOPE, WRITE_SCOPE))


# --- slugs ------------------------------------------------------------------


def test_slugify_basics():
    assert slugify("Desktop App") == "desktop-app"
    assert slugify("  Weird!! Name??  ") == "weird-name"
    assert slugify("") == "context"
    assert slugify("!!!") == "context"


def test_slug_collisions_get_suffixed(seed):
    ps = seed.store.projects
    a = ps.create_project("Same Name", owner_user_id=seed.alice_user_id)
    b = ps.create_project("Same Name", owner_user_id=seed.alice_user_id)
    assert a.slug == "same-name"
    assert b.slug == "same-name-2"


# --- listing ----------------------------------------------------------------


def test_list_user_contexts_shape(seed):
    contexts = seed.store.projects.list_user_contexts(seed.alice_user_id)
    assert len(contexts) == 1
    c = contexts[0]
    assert c["name"] == "Shared Desktop App"
    assert c["role"] == "owner"
    assert c["access"] == "owner"
    assert c["member_count"] == 2
    assert c["revision"] == 0


def test_list_excludes_other_tenants(seed):
    # carol's project must not appear for alice
    names = {c["name"] for c in seed.store.projects.list_user_contexts(seed.alice_user_id)}
    assert "Carol Solo Project" not in names


def test_bob_sees_shared_context_as_edit(seed):
    contexts = seed.store.projects.list_user_contexts(seed.bob_user_id)
    assert [c["access"] for c in contexts] == ["edit"]


# --- name / slug / id resolution -------------------------------------------


def test_resolve_by_name_slug_and_id(seed):
    ps = seed.store.projects
    pid = seed.project_id
    assert ps.resolve_context_ref(seed.alice_user_id, "Shared Desktop App") == pid
    assert ps.resolve_context_ref(seed.alice_user_id, "shared desktop app") == pid
    assert ps.resolve_context_ref(seed.alice_user_id, "shared-desktop-app") == pid
    assert ps.resolve_context_ref(seed.alice_user_id, pid) == pid


def test_resolve_refuses_other_tenants_context_by_id(seed):
    # alice knows carol's project id but is not a member
    with pytest.raises(ForbiddenError):
        seed.store.projects.resolve_context_ref(
            seed.alice_user_id, seed.other_project_id
        )


def test_resolve_refuses_other_tenants_context_by_name(seed):
    with pytest.raises(ForbiddenError):
        seed.store.projects.resolve_context_ref(
            seed.alice_user_id, "Carol Solo Project"
        )


def test_resolve_ambiguous_name_lists_candidates(seed):
    ps = seed.store.projects
    ps.create_project("Duplicate", owner_user_id=seed.alice_user_id)
    ps.create_project("Duplicate", owner_user_id=seed.alice_user_id)
    with pytest.raises(ValidationError) as exc:
        ps.resolve_context_ref(seed.alice_user_id, "Duplicate")
    assert "ambiguous" in str(exc.value)
    assert "duplicate-2" in str(exc.value)


def test_resolve_unknown_ref(seed):
    with pytest.raises(ForbiddenError):
        seed.store.projects.resolve_context_ref(seed.alice_user_id, "nope")


# --- bindings ---------------------------------------------------------------


def test_binding_roundtrip_client_level(seed):
    ps = seed.store.projects
    assert ps.get_binding(seed.alice_user_id, seed.alice_conn) is None
    ps.set_binding(seed.alice_user_id, seed.project_id, seed.alice_conn)
    assert ps.get_binding(seed.alice_user_id, seed.alice_conn) == seed.project_id


def test_binding_upsert_does_not_duplicate(seed):
    ps = seed.store.projects
    other = ps.create_project("Second", owner_user_id=seed.alice_user_id)
    ps.set_binding(seed.alice_user_id, seed.project_id, seed.alice_conn)
    ps.set_binding(seed.alice_user_id, other.id, seed.alice_conn)
    assert ps.get_binding(seed.alice_user_id, seed.alice_conn) == other.id


def test_chat_binding_overrides_client_binding(seed):
    ps = seed.store.projects
    other = ps.create_project("Second", owner_user_id=seed.alice_user_id)
    ps.set_binding(seed.alice_user_id, seed.project_id, seed.alice_conn)
    ps.set_binding(seed.alice_user_id, other.id, seed.alice_conn, "chat-2")

    p = _principal(seed)
    # no session_ref -> client default
    assert resolve_context(seed.store, p) == seed.project_id
    # that one chat -> its own context
    assert resolve_context(seed.store, p, session_ref="chat-2") == other.id
    # a different chat falls back to the client default
    assert resolve_context(seed.store, p, session_ref="chat-9") == seed.project_id


# --- precedence -------------------------------------------------------------


def test_explicit_context_wins_over_binding(seed):
    ps = seed.store.projects
    other = ps.create_project("Second", owner_user_id=seed.alice_user_id)
    ps.set_binding(seed.alice_user_id, seed.project_id, seed.alice_conn)
    assert resolve_context(seed.store, _principal(seed), context="Second") == other.id


def test_single_membership_resolves_without_binding(seed):
    assert resolve_context(seed.store, _principal(seed, "bob")) == seed.project_id


def test_multiple_contexts_without_binding_needs_selection(seed):
    seed.store.projects.create_project("Second", owner_user_id=seed.alice_user_id)
    with pytest.raises(NeedsContextSelection) as exc:
        resolve_context(seed.store, _principal(seed))
    names = {c["name"] for c in exc.value.contexts}
    assert names == {"Shared Desktop App", "Second"}


def test_no_memberships_needs_selection_with_empty_list(seed):
    uid = seed.store.projects.create_user("nobody@example.com")
    with pytest.raises(NeedsContextSelection) as exc:
        resolve_context(seed.store, Principal(uid, None))
    assert exc.value.contexts == []
    assert "create one" in str(exc.value)


def test_env_default_ignored_in_auth_mode(seed, monkeypatch):
    """SAC_DEFAULT_PROJECT_ID must not outrank real membership in production."""
    monkeypatch.setenv("SAC_AUTH_MODE", "auth")
    monkeypatch.setenv("SAC_DEFAULT_PROJECT_ID", seed.other_project_id)
    seed.store.projects.create_project("Second", owner_user_id=seed.alice_user_id)
    # would previously have silently returned carol's project
    with pytest.raises(NeedsContextSelection):
        resolve_context(seed.store, _principal(seed))


def test_env_default_still_works_in_dev_mode(seed, monkeypatch):
    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    monkeypatch.setenv("SAC_DEFAULT_PROJECT_ID", seed.project_id)
    seed.store.projects.create_project("Second", owner_user_id=seed.alice_user_id)
    assert resolve_context(seed.store, _principal(seed)) == seed.project_id


def test_deprecated_project_id_alias_still_resolves(seed, monkeypatch):
    monkeypatch.setenv("SAC_AUTH_MODE", "dev")
    identity = resolve_identity(
        seed.store, actor_email="alice@example.com", project_id=seed.project_id
    )
    assert identity.project_id == seed.project_id
