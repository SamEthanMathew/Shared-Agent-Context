"""Compiler v2: sections, memory IDs, budget accounting, manifest, §26 budgets."""
from __future__ import annotations

from app.context import CHARS_PER_TOKEN, compile_context


def _session(seed, user_id, ref):
    return seed.store.sessions.get_or_create(seed.project_id, user_id, ref)


def test_compiled_lines_include_memory_ids(seed):
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision", summary="Use Supabase Auth."
    )
    sess = _session(seed, seed.bob_user_id, "claude-main")
    result = compile_context(seed.store, seed.bob, sess, "design the auth layer")
    assert f"id={out['memory'].id}" in result["context_text"]
    assert "Supabase" in result["context_text"]


def test_sections_render(seed):
    seed.store.memories.remember(seed.alice, scope="shared", kind="decision", summary="Shared decision.")
    seed.store.memories.remember(seed.bob, scope="private", kind="note", summary="Bob private note.")
    sess = _session(seed, seed.bob_user_id, "claude-main")
    text = compile_context(seed.store, seed.bob, sess, "plan work")["context_text"]
    assert "SAC PROJECT CONTEXT" in text
    assert "CURRENT TASK" in text
    assert "SHARED CONTEXT" in text
    assert "PRIVATE CONTEXT (visible only to you)" in text
    assert "USAGE" in text


def test_private_section_only_shows_own(seed):
    # alice private must never appear in bob's compile
    a_priv = seed.store.memories.remember(seed.alice, scope="private", kind="note", summary="Alice secret plan.")
    sess = _session(seed, seed.bob_user_id, "claude-main")
    text = compile_context(seed.store, seed.bob, sess, "plan")["context_text"]
    assert a_priv["memory"].id not in text
    assert "Alice secret plan." not in text


def test_conflict_section(seed):
    a = seed.store.memories.remember(seed.alice, scope="shared", kind="decision", summary="Use Firebase.")
    seed.store.memories.remember(
        seed.bob, scope="shared", kind="decision", summary="Use Supabase.",
        contradicts=[a["memory"].id],
    )
    sess = _session(seed, seed.alice_user_id, "chatgpt-main")
    text = compile_context(seed.store, seed.alice, sess, "auth")["context_text"]
    assert "CONFLICTS (unresolved)" in text


def test_budget_is_respected_including_footer(seed):
    # many memories, tiny budget: output must not exceed budget chars
    for i in range(40):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="finding",
            summary=f"Finding number {i} about the authentication subsystem design.",
        )
    sess = _session(seed, seed.bob_user_id, "claude-main")
    budget = 600
    result = compile_context(seed.store, seed.bob, sess, "authentication design", budget_tokens=budget)
    assert len(result["context_text"]) <= budget * CHARS_PER_TOKEN
    # the footer survived truncation
    assert "USAGE" in result["context_text"]


def test_different_budgets_are_nested(seed):
    # §26 different budgets: small-budget included set ⊆ large-budget set
    for i in range(30):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="finding",
            summary=f"Auth finding {i} about tokens sessions and passkeys.",
        )
    sess_small = _session(seed, seed.bob_user_id, "s-small")
    sess_large = _session(seed, seed.bob_user_id, "s-large")
    small = compile_context(seed.store, seed.bob, sess_small, "auth tokens", budget_tokens=500)
    large = compile_context(seed.store, seed.bob, sess_large, "auth tokens", budget_tokens=5000)
    small_ids = set(small["included_memory_ids"])
    large_ids = set(large["included_memory_ids"])
    assert small_ids
    assert small_ids <= large_ids


def test_snapshot_and_manifest_recorded(seed):
    seed.store.memories.remember(seed.alice, scope="shared", kind="decision", summary="Decision X.")
    # alice has a private memory that bob can't see -> should appear as an
    # aggregate 'not_visible_private_other' exclusion in bob's manifest
    seed.store.memories.remember(seed.alice, scope="private", kind="note", summary="Alice private.")
    sess = _session(seed, seed.bob_user_id, "claude-main")
    result = compile_context(seed.store, seed.bob, sess, "decision")
    snap = seed.store.snapshots.get(result["snapshot_id"])
    assert snap is not None
    assert len(snap["included"]) >= 1
    reasons = {e.get("reason") for e in snap["excluded"]}
    assert "not_visible_private_other" in reasons


def test_compile_emits_audit_event(seed):
    seed.store.memories.remember(seed.alice, scope="shared", kind="decision", summary="Decision Y.")
    sess = _session(seed, seed.bob_user_id, "claude-main")
    compile_context(seed.store, seed.bob, sess, "decision")
    actions = {a["action"] for a in seed.store.audit.recent(seed.project_id)}
    assert "context.compile" in actions
