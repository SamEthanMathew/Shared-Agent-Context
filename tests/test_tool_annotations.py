"""Tool annotations, which two directories reject submissions over.

Anthropic's connector review requires every tool to carry a ``title`` and the
applicable ``readOnlyHint`` or ``destructiveHint``; OpenAI's app review asks for
the same plus ``openWorldHint``. Neither failure is visible at runtime -- the
server works perfectly with no annotations at all -- so without these tests a
rename or a new tool silently costs a listing weeks later.

The hints are also load-bearing for users today. ``destructiveHint`` defaults to
TRUE for anything not read-only, so an unannotated write tool tells the host that
"remember this decision" might destroy something.
"""
from __future__ import annotations

import asyncio

import pytest

from app.main import build_mcp

# Tools that change state. Everything else must be read-only. Listed explicitly
# rather than derived, so adding a writing tool fails here until someone has
# thought about what it destroys.
WRITERS = {
    "sac_create_context",
    "sac_use_context",
    "sac_sync_context",
    "sac_remember_shared",
    "sac_remember_private",
}


@pytest.fixture(scope="module")
def tools():
    mcp = build_mcp()
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


def _wire(tool) -> dict:
    """Annotations exactly as they go over the wire, camelCase and all."""
    if tool.annotations is None:
        return {}
    return tool.annotations.model_dump(by_alias=True, exclude_none=True)


def test_every_tool_has_a_title(tools):
    missing = [n for n, t in tools.items() if not _wire(t).get("title")]
    assert not missing, f"Anthropic rejects tools with no title: {missing}"


def test_titles_are_written_for_people(tools):
    """A title is what a person sees in a permission prompt, not an identifier."""
    for name, tool in tools.items():
        title = _wire(tool)["title"]
        assert "_" not in title, f"{name}: {title!r} looks like an identifier"
        assert title[0].isupper(), f"{name}: {title!r} should read as a phrase"


def test_titles_are_unique(tools):
    """Two tools sharing a title makes a permission prompt ambiguous."""
    seen: dict[str, str] = {}
    for name, tool in tools.items():
        title = _wire(tool)["title"]
        assert title not in seen, f"{name} and {seen[title]} share the title {title!r}"
        seen[title] = name


def test_every_tool_declares_read_only_or_destructive(tools):
    for name, tool in tools.items():
        w = _wire(tool)
        assert "readOnlyHint" in w or "destructiveHint" in w, f"{name} declares neither"


def test_writers_and_readers_agree_with_the_list(tools):
    for name, tool in tools.items():
        read_only = _wire(tool).get("readOnlyHint", False)
        if name in WRITERS:
            assert not read_only, f"{name} changes state but claims to be read-only"
        else:
            assert read_only, f"{name} is not in WRITERS so it must be read-only"


def test_writers_state_that_they_destroy_nothing(tools):
    """Left unset this defaults to true, which is both wrong and noisy.

    Nothing in Osmos deletes memory -- superseding marks a revision replaced and
    both stay readable -- so every writer can honestly say so. A new tool that
    genuinely destroys something should fail this and be given its own hint.
    """
    for name in WRITERS:
        w = _wire(tools[name])
        assert w.get("destructiveHint") is False, (
            f"{name} leaves destructiveHint unset, so hosts assume it destroys data"
        )


def test_nothing_reaches_the_open_world(tools):
    """Every tool acts only on the caller's own contexts.

    OpenAI's review asks for this explicitly. If a tool ever calls out to the
    public internet, this test should fail rather than the claim quietly becoming
    untrue.
    """
    for name, tool in tools.items():
        assert _wire(tool).get("openWorldHint") is False, f"{name} does not declare it"


def test_read_only_tools_are_safe_to_retry(tools):
    for name, tool in tools.items():
        if name in WRITERS:
            continue
        assert _wire(tool).get("idempotentHint") is True, f"{name} should be retryable"
