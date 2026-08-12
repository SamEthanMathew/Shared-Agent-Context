"""§26: cross-user retrieval (both directions), private isolation, project isolation."""
from __future__ import annotations

import pytest

from app.errors import ForbiddenError
from app.identity import Principal


def _ids(mems):
    return {m.id for m in mems}


def test_cross_user_retrieval_forward(seed):
    # alice writes shared; bob (member) sees it in his candidates
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Use Supabase Auth."
    )
    bob_candidates = seed.store.memories.compile_candidates(seed.project_id, seed.bob_user_id)
    assert out["memory"].id in _ids(bob_candidates)


def test_cross_user_retrieval_reverse(seed):
    # bob writes shared constraint; alice sees it
    out = seed.store.memories.remember(
        seed.bob, scope="shared", kind="constraint",
        summary="Windows needs a platform credential adapter.",
    )
    alice_candidates = seed.store.memories.compile_candidates(seed.project_id, seed.alice_user_id)
    assert out["memory"].id in _ids(alice_candidates)


def test_private_isolation_candidates(seed):
    # alice writes a private memory; bob never sees it anywhere
    out = seed.store.memories.remember(
        seed.alice, scope="private", kind="note", summary="Alice private hypothesis."
    )
    mid = out["memory"].id
    assert mid not in _ids(seed.store.memories.compile_candidates(seed.project_id, seed.bob_user_id))
    assert mid not in _ids(seed.store.memories.list_memories(seed.project_id, seed.bob_user_id))
    assert seed.store.memories.get_memory(seed.project_id, mid, seed.bob_user_id) is None
    # but alice herself sees it
    assert seed.store.memories.get_memory(seed.project_id, mid, seed.alice_user_id) is not None


def test_private_isolation_changes_feed(seed):
    out = seed.store.memories.remember(
        seed.alice, scope="private", kind="note", summary="Alice private."
    )
    delivered, _ = seed.store.memories.changes_since(
        seed.project_id, seed.bob_user_id, None, 0
    )
    assert out["memory"].id not in _ids(delivered)


def test_project_isolation_resolve(seed):
    # carol is not a member of alice/bob's project → ForbiddenError, no leakage
    carol = seed.store.projects.get_user_by_email("carol@example.com")
    with pytest.raises(ForbiddenError):
        seed.store.resolve_identity(Principal(carol["id"], None), seed.project_id)


def test_project_isolation_no_cross_project_read(seed):
    # a memory in the OTHER project is invisible when querying THIS project
    out = seed.store.memories.remember(
        seed.carol, scope="shared", kind="decision", summary="Carol project decision."
    )
    # alice queries her own project — carol's memory (other project) absent
    assert out["memory"].id not in _ids(
        seed.store.memories.compile_candidates(seed.project_id, seed.alice_user_id)
    )
