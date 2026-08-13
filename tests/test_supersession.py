"""§26 supersession + minimal conflict (contradicts) behavior."""
from __future__ import annotations

import pytest

from app.errors import ForbiddenError


def test_supersede_flips_status_and_records_relation(seed):
    old = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Use Firebase."
    )
    new = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Migrate to Supabase.",
        supersedes=[old["memory"].id],
    )
    assert new["superseded"] == [old["memory"].id]

    # old is now superseded, points to new, and gained a version
    old_now = seed.store.memories.get_memory(seed.project_id, old["memory"].id, seed.alice_user_id)
    assert old_now.status == "superseded"
    assert old_now.superseded_by_id == new["memory"].id
    assert old_now.version == 2

    versions = seed.store.memories.get_versions(old["memory"].id, seed.project_id, seed.alice_user_id)
    assert {v["version"] for v in versions} == {1, 2}

    # compile candidates include only the active (new) one
    active_ids = {m.id for m in seed.store.memories.compile_candidates(seed.project_id, seed.alice_user_id)}
    assert new["memory"].id in active_ids
    assert old["memory"].id not in active_ids

    # a supersedes relation exists
    rels = seed.store.memories.get_relations(new["memory"].id, seed.project_id, seed.alice_user_id)
    assert any(r["relation_type"] == "supersedes" and r["to_memory_id"] == old["memory"].id for r in rels)


def test_contradicts_keeps_both_active_and_surfaces_conflict(seed):
    a = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="We will use Firebase."
    )
    b = seed.store.memories.remember(
        seed.bob, scope="shared", kind="decision", summary="We decided on Supabase.",
        contradicts=[a["memory"].id],
    )
    assert b["conflicts_opened"] == [a["memory"].id]
    # both remain active
    assert seed.store.memories.get_memory(seed.project_id, a["memory"].id, seed.alice_user_id).status == "active"
    assert seed.store.memories.get_memory(seed.project_id, b["memory"].id, seed.alice_user_id).status == "active"
    # conflict surfaced
    conflicts = seed.store.memories.unresolved_conflicts(seed.project_id, seed.alice_user_id)
    assert len(conflicts) == 1
    pair_ids = {conflicts[0][0].id, conflicts[0][1].id}
    assert pair_ids == {a["memory"].id, b["memory"].id}


def test_cannot_supersede_another_users_private(seed):
    priv = seed.store.memories.remember(
        seed.bob, scope="private", kind="note", summary="Bob's private plan."
    )
    with pytest.raises(ForbiddenError):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="decision", summary="Override.",
            supersedes=[priv["memory"].id],
        )


def test_owner_can_supersede_own_private(seed):
    priv = seed.store.memories.remember(
        seed.bob, scope="private", kind="note", summary="Bob's old note."
    )
    new = seed.store.memories.remember(
        seed.bob, scope="private", kind="note", summary="Bob's new note.",
        supersedes=[priv["memory"].id],
    )
    assert new["superseded"] == [priv["memory"].id]
