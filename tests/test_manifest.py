"""What the compiler may never drop quietly, and what the record must admit to.

Two failures live here, and they are the same failure seen from either end.

The first is inside the window: an agent shown one side of an open contradiction,
with nothing to say the other side exists, acts on it as settled fact. Until this
change the packer applied one budget test to everything, so a conflict could be
dropped with reason "budget" — the size of somebody's token allowance deciding
which claim the project appears to hold. docs/DYNAMIC_MODEL_AWARE_CONTEXT_
COMPACTION.md:944-956 and :1443-1444 are explicit that mandatory content fails
loudly instead.

The second is outside it: the snapshot recorded what got IN, so "why didn't my
agent know that?" had no answer. A memory that was never visible, one beaten in
ranking, one that had faded, and one the budget could not fit all looked
identical afterwards — namely absent. Every assertion about the funnel below is
really an assertion that those four are now distinguishable.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import update

from app.api import impl
from app.context import CHARS_PER_TOKEN, TRUNCATED_NOTE, compile_context
from app.db import memories as memories_table, utcnow
from app.models import FULL, SUMMARY, TRACE, MemoryRecord


# --- helpers -----------------------------------------------------------------


def _write(seed, identity=None, **kwargs) -> str:
    fields = {"scope": "shared", "kind": "note", "summary": "Something happened."}
    fields.update(kwargs)
    return seed.store.memories.remember(identity or seed.bob, **fields)["memory"].id


def _conflict(seed, first_summary: str, second_summary: str) -> tuple[str, str]:
    first = _write(seed, kind="decision", summary=first_summary)
    second = seed.store.memories.remember(
        seed.bob, scope="shared", kind="decision", summary=second_summary,
        contradicts=[first],
    )["memory"].id
    return first, second


def _settled_session(seed, ref: str, identity=None):
    """A session that has already seen everything, so the change feed is empty
    and the sections the packer governs are the ones under test."""
    identity = identity or seed.bob
    session = seed.store.sessions.get_or_create(
        seed.project_id, identity.user_id, ref
    )
    seed.store.sessions.advance_watermark(
        session.id, seed.store.current_revision(seed.project_id)
    )
    return seed.store.sessions.get(session.id)


def _compile(seed, task: str, ref: str = "chat", identity=None, budget_tokens=3000):
    identity = identity or seed.bob
    return compile_context(
        seed.store, identity, _settled_session(seed, ref, identity), task,
        budget_tokens=budget_tokens,
    )


def _age(seed, memory_id: str, days: float) -> None:
    when = utcnow() - timedelta(days=days)
    with seed.store.engine.begin() as conn:
        conn.execute(
            update(memories_table)
            .where(memories_table.c.id == memory_id)
            .values(created_at=when, updated_at=when)
        )


def _reasons(snapshot, reason: str) -> list[dict]:
    return [e for e in snapshot["excluded"] if e.get("reason") == reason]


# --- protected content -------------------------------------------------------


def test_an_unresolved_conflict_is_never_dropped_for_budget(seed):
    """The bug this task exists to fix: admit() applied one budget test to
    everything, so on a tight sync the CONFLICTS section was as droppable as a
    stale note — and the agent had no way to tell it had happened.
    """
    left, right = _conflict(
        seed,
        "Rate limiting is enforced per account across every connection.",
        "Rate limiting is enforced per connection, not per account.",
    )
    # A wall of well-scoring memory that would otherwise crowd the pair out.
    for i in range(30):
        _write(seed, kind="finding", importance=0.7,
               summary=f"Finding {i} about rate limiting under sustained load.")

    result = _compile(seed, "rate limiting", budget_tokens=600)
    snapshot = seed.store.snapshots.get(result["snapshot_id"])

    assert left in result["included_memory_ids"]
    assert right in result["included_memory_ids"]
    assert f"id={left}" in result["context_text"]
    assert f"id={right}" in result["context_text"]
    # ...and this was a genuinely tight budget, not a roomy one in disguise.
    assert _reasons(snapshot, "budget")
    assert len(result["context_text"]) <= 600 * CHARS_PER_TOKEN


def test_a_conflict_is_shortened_before_anything_else_is_squeezed(seed):
    """Protection is not a promise of the full rung.

    A contradiction the reader can see stated is worth more than the provenance
    that would not fit beside it, so the packer degrades a protected memory to
    one whole line before it starts dropping other people's memory for it. What
    it may never do is degrade it to a trace, which drops `auth=` and the author
    — exactly what makes a disputed claim adjudicable rather than merely visible.
    """
    # Three open arguments, each with the body a real decision carries. Their
    # summary lines fit the budget; their bodies are several times over it.
    body = "The reasoning, at the length a real one runs to. " * 20
    disputed = []
    for subject in ("retries", "batch size", "dead letters"):
        left = _write(seed, kind="decision", details=body,
                      summary=f"The importer {subject} setting is the old one.")
        right = seed.store.memories.remember(
            seed.bob, scope="shared", kind="decision", details=body,
            summary=f"The importer {subject} setting was changed last week.",
            contradicts=[left],
        )["memory"].id
        disputed += [left, right]
    for i in range(20):
        _write(seed, kind="finding", summary=f"Importer finding {i} about retries.")

    result = _compile(seed, "importer settings", budget_tokens=500)
    snapshot = seed.store.snapshots.get(result["snapshot_id"])
    rungs = {e["memory_id"]: e["resolution"] for e in snapshot["included"]}

    assert all(rungs[memory_id] == SUMMARY for memory_id in disputed)
    assert result["manifest"]["protected_degraded"] == len(disputed)
    assert body not in result["context_text"]
    # The squeeze was real, and it was the bodies that gave way, not the pairs.
    assert _reasons(snapshot, "budget")
    # The whole memory is still there; only this rendering of it was shortened.
    assert seed.store.memories.get_memory(
        seed.project_id, disputed[0], seed.bob_user_id
    ).details == body.strip()


def test_a_budget_that_cannot_hold_the_conflicts_is_refused_not_truncated(seed):
    """§14.4: when mandatory content alone will not fit, SAC must not silently
    discard it.

    Failing is the kinder answer. An agent told its budget is too small raises it
    and gets the whole picture; an agent handed half an argument has no way to
    know there was ever an argument. So: no context text at all, a required size
    it can act on, and the reason named.
    """
    left, right = _conflict(
        seed,
        "Customer records are deleted thirty days after account closure. " * 12,
        "Customer records are retained for seven years after closure. " * 12,
    )

    result = _compile(seed, "retention policy", budget_tokens=500)

    assert result["ok"] is False
    assert result["error"] == "budget_unsatisfiable"
    assert result["required_tokens"] > 500
    assert sorted(result["protected_memory_ids"]) == sorted([left, right])
    # Nothing was compiled, so nothing can have been quietly left out of it.
    assert "context_text" not in result
    assert result["suggestions"]

    # The refusal is on the record too, or the only trace of it would be an
    # error message in a chat log nobody keeps.
    snapshot = seed.store.snapshots.get(result["snapshot_id"])
    assert snapshot["included"] == []
    assert snapshot["funnel"]["budget_unsatisfiable"] is True
    assert snapshot["funnel"]["required_tokens"] == result["required_tokens"]


def test_a_refused_sync_does_not_advance_the_session_watermark(seed):
    """Otherwise the loud failure becomes the silent loss it exists to prevent:
    the changes this sync could not deliver would be marked as handed over, and
    the next sync — even with a generous budget — would never offer them again.
    """
    _conflict(
        seed,
        "Deploys go out on Fridays after the soak test passes. " * 12,
        "Deploys never go out on a Friday under any circumstances. " * 12,
    )
    before = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-refused"
    ).last_seen_revision

    result = impl.sync_context(
        seed.store, seed.bob, task="deploy schedule",
        session_ref="chat-refused", budget_tokens=500,
    )
    after = seed.store.sessions.get_or_create(
        seed.project_id, seed.bob_user_id, "chat-refused"
    ).last_seen_revision

    assert result["ok"] is False and result["error"] == "budget_unsatisfiable"
    assert after == before

    # And the same sync, given the room it asked for, delivers them.
    retry = impl.sync_context(
        seed.store, seed.bob, task="deploy schedule", session_ref="chat-refused",
        budget_tokens=max(500, result["required_tokens"]),
    )
    assert retry["ok"] is True
    assert "never go out on a Friday" in retry["context_text"]


def test_a_task_too_long_for_its_own_budget_is_refused(seed):
    """The current task is protected too, and it is the one piece of mandatory
    content that cannot be degraded at all — it is the caller's own words.

    This used to emit a header longer than the budget and report a token count
    that exceeded the budget it was given, which is the same silent overrun in
    the opposite direction.
    """
    result = _compile(seed, "auth " * 500, budget_tokens=500)

    assert result["error"] == "budget_unsatisfiable"
    assert result["required_tokens"] > 500


# --- the funnel --------------------------------------------------------------


def test_the_manifest_counts_add_up_to_what_actually_happened(seed):
    """Every candidate ends in exactly one bucket. If these stop summing, some
    memory is being lost between the stages and the record would not show it.
    """
    fresh = [
        _write(seed, kind="finding", summary=f"Finding {i} about the search index.")
        for i in range(12)
    ]
    stale = [
        _write(seed, kind="observation", importance=0.3,
               summary=f"The search index rebuilt cleanly on day {i}.")
        for i in range(4)
    ]
    for memory_id in stale:
        _age(seed, memory_id, 400)

    result = _compile(seed, "search index", budget_tokens=700)
    snapshot = seed.store.snapshots.get(result["snapshot_id"])
    funnel = snapshot["funnel"]

    assert funnel["planned"] == (
        funnel["included"] + funnel["omitted_faded"] + funnel["dropped_budget"]
    )
    assert sum(funnel["resolutions"].values()) == funnel["included"]
    assert funnel["included"] == len(snapshot["included"])
    assert funnel["omitted_faded"] == len(_reasons(snapshot, "faded")) == len(stale)
    assert funnel["dropped_budget"] == len(_reasons(snapshot, "budget"))
    assert funnel["candidates_considered"] >= funnel["planned"] == len(fresh) + len(stale)
    assert funnel["resolutions"][SUMMARY] >= 1
    assert funnel["budget_unsatisfiable"] is False


def test_the_manifest_says_which_rung_each_included_memory_was_rendered_at(seed):
    """"Degraded to a trace" and "not included" are different answers to "why
    didn't my agent use that", and the record has to be able to tell them apart.
    """
    whole = _write(seed, identity=seed.alice, kind="decision",
                   summary="Postgres is the production database.",
                   details="Chosen for the extension ecosystem.")
    faded = _write(seed, kind="observation", importance=0.3,
                   summary="The nightly reindex of the production database "
                           "finished in eleven minutes and touched every table.")
    _age(seed, faded, 20)

    funnel = _compile(seed, "production database")["manifest"]

    assert funnel["resolutions"][FULL] == 1
    assert funnel["resolutions"][TRACE] == 1
    assert funnel["included"] == 2
    assert whole and faded  # both are still stored, whatever the rungs say


def test_a_truncated_sync_says_so_in_the_response_and_in_the_text(seed):
    """An agent cannot report what it was not told. The response carries the
    counts so it can say "I only got part of this"; the text carries the sentence
    so the model reading it knows before it answers.
    """
    for i in range(40):
        _write(seed, kind="finding", importance=0.7,
               summary=f"Finding {i} about the checkout flow and its retry logic.")

    tight = _compile(seed, "checkout flow", ref="tight", budget_tokens=600)
    roomy = _compile(seed, "checkout flow", ref="roomy", budget_tokens=20000)

    assert tight["context_truncated"] is True
    assert tight["manifest"]["dropped_budget"] > 0
    assert TRUNCATED_NOTE in tight["context_text"]
    assert len(tight["context_text"]) <= 600 * CHARS_PER_TOKEN

    assert roomy["context_truncated"] is False
    assert TRUNCATED_NOTE not in roomy["context_text"]


def test_other_members_private_memory_is_counted_and_never_named(seed):
    """The privacy property the manifest has always had, now that the manifest
    reports more: a funnel that answered "why didn't I see that" by naming the
    private memory of the person who wrote it would be a disclosure with a
    helpful tone of voice.
    """
    hidden = [
        seed.store.memories.remember(
            seed.alice, scope="private", kind="note",
            summary=f"Alice's private note {i} about the acquisition.",
        )["memory"].id
        for i in range(3)
    ]

    result = _compile(seed, "acquisition")
    snapshot = seed.store.snapshots.get(result["snapshot_id"])
    written = json.dumps(
        {"f": snapshot["funnel"], "i": snapshot["included"], "e": snapshot["excluded"]}
    )

    assert snapshot["funnel"]["filtered_permission"] == 3
    assert _reasons(snapshot, "not_visible_private_other")[0]["count"] == 3
    for memory_id in hidden:
        assert memory_id not in written
    assert "acquisition" not in written.replace(result["snapshot_id"], "")


def test_the_funnel_separates_being_outranked_from_being_a_duplicate(seed):
    """"Nothing better was found" and "you already said that" are different
    answers, and only the ranker can tell them apart — which is why it fills the
    count in on the way past rather than the compiler guessing afterwards.
    """
    now = utcnow()

    def record(memory_id: str, summary: str) -> MemoryRecord:
        return MemoryRecord(
            id=memory_id, project_id="p", revision=1, scope="shared",
            owner_user_id=None, kind="finding", summary=summary, details="",
            tags=[], status="active", importance=0.6, confidence=0.7,
            authority="member", sensitivity="internal", version=1,
            superseded_by_id=None, created_by_user_id="u", created_by_agent_id=None,
            origin_session_id=None, source_event_id=None, valid_from=None,
            valid_until=None, created_at=now, updated_at=now,
            search_text=summary.lower(),
        )

    # Twenty copies of the answer, and eighty other things — more than the cap,
    # so the selection has to leave something out and it matters which.
    duplicates = [
        record(f"dup{i}", "the checkout retry uses exponential backoff")
        for i in range(20)
    ]
    others = [record(f"other{i}", f"unrelated subject number {i} entirely")
              for i in range(80)]

    stats: dict[str, int] = {}
    chosen = seed.store.memories.rank_scored(
        duplicates + others, "checkout retry backoff", limit=50, stats=stats
    )

    assert len(chosen) == 50
    assert stats["redundant"] > 0
    # Only near-duplicates are counted: the unrelated memories that missed the
    # cap were outranked, which is not the same complaint.
    assert stats["redundant"] <= len(duplicates)
