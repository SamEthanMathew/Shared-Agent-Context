"""§26 revision sync + regressions for the two known change-feed bugs."""
from __future__ import annotations


def _shared(seed, identity, summary, **kw):
    return seed.store.memories.remember(
        identity, scope="shared", kind=kw.pop("kind", "finding"), summary=summary, **kw
    )


def test_revision_sync_delivers_new_change(seed):
    # bob synced at r0; alice writes r1; bob's changes deliver it
    out = _shared(seed, seed.alice, "New decision at r1.")
    delivered, truncated = seed.store.memories.changes_since(
        seed.project_id, seed.bob_user_id, None, 0
    )
    assert out["memory"].id in {m.id for m in delivered}
    assert truncated is False


def test_self_echo_excluded_but_others_receive(seed):
    # alice's session writes; alice's OWN session must not see it, bob must
    sess = seed.store.sessions.get_or_create(seed.project_id, seed.alice_user_id, "chatgpt-main")
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="finding", summary="Alice finding.",
        session_id=sess.id,
    )
    own, _ = seed.store.memories.changes_since(
        seed.project_id, seed.alice_user_id, sess.id, 0
    )
    assert out["memory"].id not in {m.id for m in own}
    # bob (different session) receives it
    bob_changes, _ = seed.store.memories.changes_since(
        seed.project_id, seed.bob_user_id, None, 0
    )
    assert out["memory"].id in {m.id for m in bob_changes}


def test_truncation_holds_watermark_back(seed):
    # write 5 shared memories; ask for changes with limit=2
    ids = [_shared(seed, seed.alice, f"memory number {i}")["memory"].id for i in range(5)]
    delivered, truncated = seed.store.memories.changes_since(
        seed.project_id, seed.bob_user_id, None, 0, limit=2
    )
    assert truncated is True
    assert len(delivered) == 2
    # the watermark advances only to the last delivered revision, not head
    last_delivered_rev = delivered[-1].revision
    assert last_delivered_rev < 5
    # simulate advancing then re-syncing: the rest arrive next round
    sess = seed.store.sessions.get_or_create(seed.project_id, seed.bob_user_id, "claude-main")
    seed.store.sessions.advance_watermark(sess.id, last_delivered_rev)
    remaining, _ = seed.store.memories.changes_since(
        seed.project_id, seed.bob_user_id, None, last_delivered_rev, limit=10
    )
    delivered_ids = {m.id for m in delivered} | {m.id for m in remaining}
    assert set(ids) <= delivered_ids  # nothing permanently lost


def test_others_private_skipped_but_watermark_can_reach_head(seed):
    # bob writes a private memory at r1; alice syncs → she doesn't receive it,
    # but not-truncated means her watermark may jump to head safely
    seed.store.memories.remember(
        seed.bob, scope="private", kind="note", summary="Bob private."
    )
    head = seed.store.current_revision(seed.project_id)
    delivered, truncated = seed.store.memories.changes_since(
        seed.project_id, seed.alice_user_id, None, 0, limit=20
    )
    assert truncated is False
    assert delivered == []  # bob's private is the only write and it's invisible
    # head is 1; since not truncated, watermark rule (in impl) would advance to head
    assert head == 1
