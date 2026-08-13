"""Does retrieval actually match the task?

The audit's finding was blunt: the task string did not participate in candidate
generation at all. ``compile_candidates`` was ``ORDER BY revision DESC LIMIT
750`` — a pure recency window — and ``rank()`` re-scored whatever recency
happened to pick. A memory that answered the task exactly but was older than 750
writes could not be retrieved by any wording of the task.

These tests measure that, rather than asserting an implementation. The labelled
set below is the point of the file: real vocabulary mismatches ("the DB choice"
-> "database: Postgres"), scored against the ranker this change replaced, which
is kept verbatim in ``_legacy_rank`` so the comparison is a measurement and not
a claim.

No embeddings are involved anywhere. Matching is lexical, the synonym table is
readable, and the one case lexical matching cannot solve is recorded as a KNOWN
MISS rather than hidden.
"""
from __future__ import annotations

import math
import re

import pytest

from app.models import AUTHORITY_WEIGHT, KIND_WEIGHT
from app.stores.memories import (
    SYNONYMS,
    SYNONYM_GROUPS,
    build_search_text,
    merge_candidates,
    task_concepts,
)


# --- the ranker this change replaced, kept as the measurement baseline --------

_LEGACY_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "into", "about", "your",
    "you", "are", "was", "were", "have", "has", "had", "will", "would", "should",
    "could", "can", "our", "their", "they", "them", "then", "than", "when", "what",
    "which", "where", "while", "how", "why", "who", "use", "using", "used", "make",
    "made", "need", "needs", "work", "working", "project", "context", "shared",
}


def _legacy_tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_\-]{3,}", (text or "").lower())
    return {w for w in words if w not in _LEGACY_STOPWORDS}


def _legacy_rank(candidates, task, limit=50):
    """Pre-B2 ``MemoryStore.rank``, copied so "better" is a measured claim.

    Kept here rather than in the store because it is not a code path any more —
    it is the yardstick. If it drifts from what shipped, the numbers in the
    report stop meaning anything, so it is frozen deliberately.
    """
    if not candidates:
        return []
    task_tokens = _legacy_tokenize(task)
    newest = max(m.revision for m in candidates)
    scored = []
    for m in candidates:
        searchable = " ".join([m.summary, " ".join(m.tags), m.kind])
        mem_tokens = _legacy_tokenize(searchable)
        overlap = len(task_tokens & mem_tokens)
        coverage = overlap / max(1, len(task_tokens))
        lexical = overlap + 2.0 * coverage
        recency = math.exp(-(newest - m.revision) / 80.0)
        score = (
            lexical * 3.0
            + m.importance * 2.0
            + recency
            + KIND_WEIGHT.get(m.kind, 1.0)
            + AUTHORITY_WEIGHT.get(m.authority, 1.0)
            + 0.5 * m.confidence
        )
        scored.append((score, m))
    scored.sort(key=lambda p: (p[0], p[1].revision), reverse=True)
    return [m for _, m in scored[: max(1, min(int(limit), 200))]]


# --- the corpus --------------------------------------------------------------

# Written first, so every one of them is older than the noise that follows. That
# ordering is the point: recency alone must not be able to find them.
TARGETS: list[tuple[str, str, list[str]]] = [
    ("decision", "Production database is Postgres 16 hosted on Render.", ["storage"]),
    ("decision", "Authentication uses passkeys via WebAuthn; passwords are gone.", ["identity"]),
    ("decision", "Deployment runs on Render, one Docker image per service.", ["shipping"]),
    ("constraint", "Kubernetes is not used; a single container per service is enough.", ["ops"]),
    ("finding", "Latency budget for the backend is 200 ms at p95.", ["speed"]),
    ("decision", "Stripe subscriptions are billed monthly per seat.", ["revenue"]),
]

# (task as a human would type it, the summary that answers it)
LABELLED: list[tuple[str, str]] = [
    ("the DB choice", TARGETS[0][1]),
    ("auth flow", TARGETS[1][1]),
    ("how do we deploy", TARGETS[2][1]),
    ("k8s", TARGETS[3][1]),
    ("api perf", TARGETS[4][1]),
    ("payments", TARGETS[5][1]),
]

# KNOWN MISS. "money" shares no word, stem or synonym with anything stored, so no
# lexical system can connect it to the Stripe memory — only a model that had read
# both could. Recorded here instead of quietly dropped from the labelled set: the
# owner ruled embeddings out, and this is precisely the gap that leaves open.
KNOWN_MISS: tuple[str, str] = ("where does the money come from", TARGETS[5][1])


def _populate(seed, noise: int = 30) -> None:
    for kind, summary, tags in TARGETS:
        seed.store.memories.remember(
            seed.alice, scope="shared", kind=kind, summary=summary, tags=tags
        )
    # Recent, high-weight, and about nothing the labelled tasks ask for. Under a
    # recency-shaped ranker this is what a sync sees instead of the answers.
    for i in range(noise):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="decision",
            summary=f"Sprint {i} retrospective was recorded by the facilitator.",
            tags=["ceremony"],
        )


def _new_ranked(seed, task, limit=10):
    candidates, _capped = seed.store.memories.candidate_set(
        seed.project_id, seed.alice_user_id, task=task
    )
    return seed.store.memories.rank(candidates, task, limit=limit)


def _legacy_ranked(seed, task, limit=10):
    candidates = seed.store.memories.compile_candidates(
        seed.project_id, seed.alice_user_id
    )
    return _legacy_rank(candidates, task, limit=limit)


def _hits(ranked, expected_summary, k):
    return any(m.summary == expected_summary for m in ranked[:k])


# --- the measurement ---------------------------------------------------------


def test_the_new_ranker_beats_the_one_it_replaces_on_the_labelled_set(seed):
    """The whole justification for this change, as a number.

    Each labelled task is a real vocabulary mismatch — an acronym, a stem, or a
    different word for the same thing. The old ranker cannot see any of them,
    because raw token overlap with an unexpanded task is zero and the score then
    collapses to recency, importance and kind, all of which favour the noise.
    """
    _populate(seed)

    old_top1 = sum(_hits(_legacy_ranked(seed, t), s, 1) for t, s in LABELLED)
    new_top1 = sum(_hits(_new_ranked(seed, t), s, 1) for t, s in LABELLED)
    old_top3 = sum(_hits(_legacy_ranked(seed, t), s, 3) for t, s in LABELLED)
    new_top3 = sum(_hits(_new_ranked(seed, t), s, 3) for t, s in LABELLED)

    assert new_top1 > old_top1, f"top-1: old {old_top1}/6, new {new_top1}/6"
    assert new_top3 > old_top3, f"top-3: old {old_top3}/6, new {new_top3}/6"
    # Not "better than nothing" — better than most of the way there.
    assert new_top1 >= 5
    assert new_top3 == len(LABELLED)


def test_the_zero_overlap_case_is_a_known_miss(seed):
    """The limit of lexical retrieval, stated rather than hidden.

    "money" is not a word, stem, or synonym of anything in the Stripe memory.
    Expansion cannot reach it and neither can stemming; only a model that had
    read both texts would connect them. The owner ruled embeddings out, so this
    stays a miss — and this test exists so it stays a *documented* one.

    The assertion is deliberately not "the memory is absent from the top three".
    When a task matches nothing, every candidate scores identically on the match
    terms and the ranking is decided entirely by recency, importance and kind —
    so the right memory can turn up in the top three by luck, and calling that
    a hit would be flattering the system. What is measured instead is that the
    task bought *nothing*: the search channel finds no rows, and the ranking is
    the same order it would have produced with no task at all.

    If someone later adds a synonym entry that closes this, the test fails and
    they have to decide deliberately whether the entry is honest or is
    overfitting to a labelled example.
    """
    _populate(seed)
    task, _expected = KNOWN_MISS

    assert (
        seed.store.memories.match_candidates(
            seed.project_id, seed.alice_user_id, task
        )
        == []
    )
    with_task = [m.id for m in _new_ranked(seed, task, limit=36)]
    without_task = [m.id for m in _new_ranked(seed, "", limit=36)]
    assert with_task == without_task


# --- candidate generation: the actual root cause -----------------------------


def test_a_relevant_memory_older_than_the_recency_window_is_still_found(
    seed, monkeypatch
):
    """The bug in one test: the recency window was the whole candidate pool.

    With the window at three, the answer is the fourth-oldest of thirty rows and
    could not be retrieved by any wording of the task. The task-match channel
    reaches past the window, so age stops being a hard cutoff.
    """
    import app.stores.memories as memories_module

    monkeypatch.setattr(memories_module, "COMPILE_CANDIDATE_LIMIT", 3)

    answer = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision",
        summary="Production database is Postgres 16 hosted on Render.",
    )["memory"].id
    for i in range(30):
        seed.store.memories.remember(
            seed.alice, scope="shared", kind="decision",
            summary=f"Sprint {i} retrospective was recorded by the facilitator.",
        )

    recency_only = seed.store.memories.compile_candidates(
        seed.project_id, seed.alice_user_id
    )
    assert answer not in {m.id for m in recency_only}

    candidates, capped = seed.store.memories.candidate_set(
        seed.project_id, seed.alice_user_id, task="the DB choice"
    )
    assert answer in {m.id for m in candidates}
    # ...and outgrowing the window is still reported, because it still happened.
    assert capped is True


def test_the_changes_set_is_always_a_candidate(seed):
    """Something that just changed is relevant by definition, task or not.

    It costs no query: the compiler has already loaded the change feed, so the
    third channel is a merge rather than a fourth round trip.
    """
    changed = seed.store.memories.remember(
        seed.alice, scope="shared", kind="note",
        summary="Facilitator rota swapped for the quarter.",
    )["memory"]

    candidates, _ = seed.store.memories.candidate_set(
        seed.project_id, seed.bob_user_id, task="the DB choice", extra=[changed]
    )

    assert changed.id in {m.id for m in candidates}


def test_merging_the_channels_keeps_one_row_per_memory(seed):
    """All three channels overlap heavily; a duplicate would be double-weighted."""
    _populate(seed, noise=3)
    matched = seed.store.memories.match_candidates(
        seed.project_id, seed.alice_user_id, "the DB choice"
    )
    recent = seed.store.memories.compile_candidates(
        seed.project_id, seed.alice_user_id
    )
    merged = merge_candidates(matched, recent, recent)

    ids = [m.id for m in merged]
    assert len(ids) == len(set(ids))
    assert set(ids) == {m.id for m in matched} | {m.id for m in recent}


# --- SECURITY: the match channel is a new way to read the database -----------


def test_a_full_text_match_never_surfaces_another_users_private_memory(seed):
    """The highest-risk part of this change.

    Every other read path carries ``_visible()``. A new retrieval path that
    forgot it would let anyone in the context read anyone else's private memory
    simply by guessing a word in it — and the search channel is *designed* to
    find rows by their words, which makes it the most effective possible probe.
    """
    private = seed.store.memories.remember(
        seed.alice, scope="private", kind="note",
        summary="Alice's private database password rotation plan.",
    )["memory"].id

    mine = seed.store.memories.match_candidates(
        seed.project_id, seed.alice_user_id, "the DB choice"
    )
    theirs = seed.store.memories.match_candidates(
        seed.project_id, seed.bob_user_id, "the DB choice"
    )

    assert private in {m.id for m in mine}
    assert private not in {m.id for m in theirs}
    # ...and it must not arrive through the composed candidate set either.
    candidates, _ = seed.store.memories.candidate_set(
        seed.project_id, seed.bob_user_id, task="the DB choice"
    )
    assert private not in {m.id for m in candidates}


def test_a_full_text_match_cannot_cross_a_membership_boundary(seed):
    """Carol is in a different context; no wording of a task may reach into it."""
    theirs = seed.store.memories.remember(
        seed.carol, scope="shared", kind="decision",
        summary="Carol's context also chose Postgres as its database.",
    )["memory"].id

    for user_id in (seed.alice_user_id, seed.bob_user_id):
        found = seed.store.memories.match_candidates(
            seed.project_id, user_id, "the DB choice"
        )
        assert theirs not in {m.id for m in found}

    # The row is genuinely findable — by the person entitled to it.
    carol_found = seed.store.memories.match_candidates(
        seed.other_project_id, seed.carol.user_id, "the DB choice"
    )
    assert theirs in {m.id for m in carol_found}


def test_a_full_text_match_ignores_retracted_and_expired_memory(seed):
    """The match channel must agree with the recency window about what is live.

    A retracted memory is a human correction; surfacing it because it happens to
    contain the task's words would undo the correction.
    """
    stale = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision",
        summary="Old decision: the database is MySQL.",
    )["memory"].id
    seed.store.memories.retract(seed.alice, stale)

    found = seed.store.memories.match_candidates(
        seed.project_id, seed.alice_user_id, "the DB choice"
    )
    assert stale not in {m.id for m in found}


def test_the_match_channel_asks_for_no_memory_bodies(seed):
    """Same reason as the other read paths: 20,000 chars a row that nobody reads."""
    from tests.test_sync_cost import counted

    _populate(seed, noise=2)
    with counted(seed.store.engine) as statements:
        seed.store.memories.match_candidates(
            seed.project_id, seed.alice_user_id, "the DB choice"
        )

    assert statements and all("memories.details" not in s for s in statements)


# --- synonym expansion -------------------------------------------------------


def test_every_synonym_group_is_symmetric(seed):
    """The table is an equivalence class, not a direction.

    "db -> database" without "database -> db" would make retrieval depend on
    which word the person happened to type, which is the failure the table is
    here to remove.
    """
    for group in SYNONYM_GROUPS:
        for word in group:
            assert set(group) <= SYNONYMS[word], word


def test_synonym_entries_survive_tokenisation(seed):
    """A two-letter acronym is exactly the case this is for.

    The tokeniser used to require three characters, which silently dropped "db",
    "ci", "ui" and "ux" — the very words a person types instead of the word the
    memory was written with.
    """
    from app.stores.memories import ordered_tokens

    for group in SYNONYM_GROUPS:
        for word in group:
            assert ordered_tokens(word) == [word], word


def test_expansion_happens_on_the_task_not_on_the_memory(seed):
    """Nothing about a memory's meaning may be stored — the owner's rule.

    The stored token string is the memory's own words, filtered and ordered.
    Expansion is a query-time operation, so what is on disk stays inspectable
    and stays exactly what the author wrote.
    """
    stored = build_search_text("The database is Postgres.", ["storage"], "decision")

    assert "db" not in stored.split()
    assert set(stored.split()) == {"database", "postgres", "storage", "decision"}
    # ...while the task side does expand.
    forms = {f for _literals, f in task_concepts("the DB choice") for f in f}
    assert {"db", "database", "postgres"} <= forms


# --- scoring -----------------------------------------------------------------


def test_a_hit_in_the_summary_outranks_a_hit_in_the_kind(seed):
    """"observation" matches every observation ever written.

    Without field weighting a task that happens to name a kind pulls in the whole
    kind ahead of the memory that is actually about the subject.
    """
    store = seed.store.memories
    store.remember(
        seed.alice, scope="shared", kind="observation",
        summary="Sprint retrospective actions were recorded.",
    )
    store.remember(
        seed.alice, scope="shared", kind="note",
        summary="Caching layer keeps the response fresh for a minute.",
    )

    ranked = _new_ranked(seed, "observation about caching", limit=2)
    assert ranked[0].summary.startswith("Caching layer")


def test_naming_a_kind_does_not_put_that_kind_first(seed):
    """The field discount has to apply to the exact-match term too.

    A kind name matches *exactly* — no synonym hop, no stem — so discounting only
    the relevance term still let the exact term hand a memory full credit for
    merely being the kind the task named. Here the lone constraint is about
    nothing relevant but is the newest row and the second-heaviest kind, while
    the memories that are genuinely about caching are older and lighter. The
    subject has to beat the grammar.

    IDF already dampens this when the named kind is common, which is why the
    corpus makes it rare — one constraint among ten notes — so the field weight
    is the only thing left doing the work.
    """
    store = seed.store.memories
    for i in range(10):
        store.remember(
            seed.alice, scope="shared", kind="note",
            summary=f"Caching layer {i} keeps the response fresh for a minute.",
        )
    store.remember(
        seed.alice, scope="shared", kind="constraint",
        summary="Quarterly budget was circulated for signature.",
    )

    ranked = _new_ranked(seed, "constraint about caching", limit=3)
    assert ranked[0].kind == "note"
    assert "Caching layer" in ranked[0].summary


def test_adjacent_task_words_beat_the_same_words_scattered(seed):
    """Two words next to each other are usually one idea; far apart they are two.

    Both memories contain both task words, so a bag-of-words score cannot
    separate them — and the wrong one is newer, so recency actively prefers it.
    """
    store = seed.store.memories
    store.remember(
        seed.alice, scope="shared", kind="finding",
        summary="Token rotation happens every thirty days.",
    )
    store.remember(
        seed.alice, scope="shared", kind="finding",
        summary="Rotation of the duty roster is unrelated to the guest token.",
    )

    ranked = _new_ranked(seed, "token rotation", limit=2)
    assert ranked[0].summary.startswith("Token rotation")


def test_near_identical_memories_do_not_fill_the_budget(seed):
    """Five copies of one fact are worth one slot, not five.

    There was no redundancy term at all, so the most relevant thing in the
    context could crowd out everything else simply by having been written five
    times — which is exactly what a chatty agent does.
    """
    store = seed.store.memories
    clone = "Release checklist requires a staging soak."
    for _ in range(5):
        store.remember(seed.alice, scope="shared", kind="decision", summary=clone)
    for other in (
        "Checklist owner is the on-call engineer.",
        "Release notes are published to the changelog.",
        "Staging mirrors the production data volume.",
    ):
        store.remember(seed.alice, scope="shared", kind="decision", summary=other)

    ranked = _new_ranked(seed, "release checklist", limit=4)

    assert sum(1 for m in ranked if m.summary == clone) == 1


def test_a_rare_word_outranks_a_common_one(seed):
    """IDF, which plain set intersection cannot express.

    Every memory here mentions the release; only one mentions the soak. A task
    naming both must be answered by the memory carrying the rare word, not by
    whichever release note happens to be newest.
    """
    store = seed.store.memories
    store.remember(
        seed.alice, scope="shared", kind="finding",
        summary="Release soak duration was measured at two hours.",
    )
    for i in range(12):
        store.remember(
            seed.alice, scope="shared", kind="decision",
            summary=f"Release {i} was announced to the wider audience.",
        )

    ranked = _new_ranked(seed, "release soak", limit=1)
    assert ranked[0].summary.startswith("Release soak")


def test_ranking_is_deterministic(seed):
    """The compiler admits ranked items in order until the budget runs out.

    A non-deterministic ranker would make a small budget's contents stop being a
    prefix of a large one's, which is the property tests/test_compile.py pins.
    """
    _populate(seed, noise=10)
    first = [m.id for m in _new_ranked(seed, "auth flow", limit=20)]
    second = [m.id for m in _new_ranked(seed, "auth flow", limit=20)]

    assert first == second


# --- precomputation ----------------------------------------------------------


def test_the_search_tokens_are_written_with_the_memory(seed):
    """Point of the column: ranking must not re-derive this 751 times a sync."""
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="decision",
        summary="The databases are Postgres.", tags=["storage"],
    )

    assert out["memory"].search_text == "databases postgres storage decision"
    stored = seed.store.memories.get_memory(
        seed.project_id, out["memory"].id, seed.alice_user_id
    )
    assert stored.search_text == out["memory"].search_text


def test_ranking_tokenises_the_task_and_nothing_else(seed):
    """~751 regex tokenisations per sync, from scratch, every call.

    The candidate's tokens were computed when it was written; the only text
    ranking has not seen before is the task.
    """
    import app.stores.memories as memories_module

    _populate(seed, noise=25)
    candidates = seed.store.memories.compile_candidates(
        seed.project_id, seed.alice_user_id
    )
    assert len(candidates) > 25

    seen: list[str] = []
    real = memories_module.ordered_tokens

    def counting(text):
        seen.append(text)
        return real(text)

    memories_module.ordered_tokens = counting
    try:
        seed.store.memories.rank(candidates, "auth flow", limit=10)
    finally:
        memories_module.ordered_tokens = real

    assert seen == ["auth flow"]


def test_a_record_without_precomputed_tokens_still_ranks(seed):
    """Rows written before the column existed, and any hand-built record.

    Ranking falls back to deriving the tokens, which is what it always did — the
    result is the same, only the cost comes back.
    """
    _populate(seed, noise=2)
    candidates = seed.store.memories.compile_candidates(
        seed.project_id, seed.alice_user_id
    )
    for m in candidates:
        m.search_text = ""

    ranked = seed.store.memories.rank(candidates, "the DB choice", limit=1)
    assert ranked[0].summary.startswith("Production database")


def test_the_search_text_never_reaches_the_api(seed):
    """It is an index, not content. Callers get the words the author wrote."""
    out = seed.store.memories.remember(
        seed.alice, scope="shared", kind="note", summary="A note about caching."
    )
    assert "search_text" not in out["memory"].as_dict()


# --- dialects ----------------------------------------------------------------


def test_the_match_channel_runs_on_sqlite(seed):
    """SQLite has no tsvector, and the whole suite plus local dev runs on it.

    The Postgres path is the fast one; this asserts the fallback is not merely
    non-crashing but actually finds the row.
    """
    assert seed.store.engine.dialect.name == "sqlite"

    _populate(seed, noise=2)
    found = seed.store.memories.match_candidates(
        seed.project_id, seed.alice_user_id, "the DB choice"
    )

    assert any(m.summary.startswith("Production database") for m in found)


def test_an_empty_task_asks_the_database_nothing(seed):
    """No terms means no match channel — not a scan that matches everything."""
    from tests.test_sync_cost import counted

    _populate(seed, noise=2)
    with counted(seed.store.engine) as statements:
        found = seed.store.memories.match_candidates(
            seed.project_id, seed.alice_user_id, "   "
        )

    assert found == []
    assert statements == []


@pytest.mark.parametrize("task", ["100% off", "a_b", "', OR 1=1 --", "-", "!!!"])
def test_odd_task_text_does_not_break_the_match_channel(seed, task):
    """The task is caller-supplied text that reaches a LIKE pattern and a tsquery.

    A LIKE wildcard or a stray quote must be data, never syntax.
    """
    _populate(seed, noise=2)
    found = seed.store.memories.match_candidates(
        seed.project_id, seed.alice_user_id, task
    )

    assert all(m.project_id == seed.project_id for m in found)
