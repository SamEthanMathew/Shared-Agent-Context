"""The directory submission pack, checked against the limits it will be pasted into.

Both portals silently truncate over-long fields. A tagline cut off mid-word is
the first thing a reviewer sees, and nothing warns you — the value is simply
shorter than what you typed. These tests read the drafted copy out of
docs/DIRECTORY_SUBMISSION.md so the document stays the single source and cannot
drift from what actually fits.

They also pin the URLs the pack promises a reviewer. A documentation link that
404s is a rejection on both sides, and /docs exists only because the pack cites
it, so nothing else in the app would notice it disappearing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PACK = Path(__file__).resolve().parents[1] / "docs" / "DIRECTORY_SUBMISSION.md"


@pytest.fixture(scope="module")
def pack() -> str:
    return PACK.read_text(encoding="utf-8")


def _fenced_after(text: str, heading: str) -> str:
    """The first fenced block following a heading, stripped."""
    start = text.index(heading)
    block = re.search(r"```\n(.*?)```", text[start:], re.S)
    assert block, f"no fenced block under {heading!r}"
    return block.group(1).strip()


def test_the_pack_exists(pack):
    assert len(pack) > 2000, "submission pack looks truncated"


def test_name_fits_the_tighter_of_the_two_limits(pack):
    """Anthropic allows 100, OpenAI 30. The name has to satisfy both."""
    name = _fenced_after(pack, "### Name")
    assert len(name) <= 30, f"{name!r} is {len(name)} chars; OpenAI caps at 30"


def test_tagline_fits(pack):
    tagline = _fenced_after(pack, "### Tagline")
    assert len(tagline) <= 55, f"{len(tagline)} chars; Anthropic caps at 55"


def test_description_fits(pack):
    desc = _fenced_after(pack, "### Description")
    assert len(desc) <= 2000, f"{len(desc)} chars; Anthropic caps at 2000"


def test_enough_example_prompts(pack):
    """Anthropic asks for at least three, exercising different tools."""
    section = pack[pack.index("## Example prompts"):pack.index("## Technical answers")]
    numbered = re.findall(r"^\d+\. \*\*", section, re.M)
    assert len(numbered) >= 3, f"only {len(numbered)} example prompts"


def test_no_placeholder_survives_into_the_listing_copy(pack):
    """Square brackets are how this repo marks something undecided.

    The reviewer-account block is exempt: it is deliberately a form to fill in
    once the account exists, not copy that gets pasted anywhere.
    """
    listing = pack[pack.index("## Listing copy"):pack.index("## Reviewer test account")]
    # A markdown link is [text](url); anything else in brackets is a TODO.
    todos = re.findall(r"\[[^\]]{3,80}\](?!\()", listing)
    assert not todos, f"unresolved placeholders in listing copy: {todos}"


@pytest.fixture(scope="module")
def client():
    from app.main import app

    return TestClient(app)


@pytest.mark.parametrize("path", ["/docs", "/privacy", "/terms", "/contact"])
def test_every_url_the_pack_promises_resolves(client, path):
    """Cited to a directory reviewer, so a 404 here is a rejected submission."""
    assert client.get(path).status_code == 200, f"{path} does not resolve"


def test_docs_page_covers_what_a_review_requires(client):
    """Setup steps, the server address, and how authorisation works."""
    body = client.get("/docs").text
    assert "https://withosmos.com/mcp" in body, "no server address on the docs page"
    for word in ("Claude", "ChatGPT", "approve"):
        assert word.lower() in body.lower(), f"docs page never mentions {word}"


def test_docs_is_reachable_from_the_site(client):
    """A page nothing links to is a page a reviewer will not find."""
    assert 'href="/docs"' in client.get("/").text, "homepage does not link to /docs"
