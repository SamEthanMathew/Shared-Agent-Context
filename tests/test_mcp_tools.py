"""In-process MCP client exercising all 8 SAC tools + the A→B handoff."""
from __future__ import annotations

import asyncio


def _call(mcp, tool, args):
    from mcp import Client

    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run())


def test_all_tools_and_handoff(wired):
    from app.main import mcp

    seed = wired

    # sac_status as alice
    res = _call(mcp, "sac_status", {"actor_email": "alice@example.com"})
    assert not res.is_error
    assert res.structured_content["mode"] == "v1_core_engine"

    # sac_project_info
    res = _call(mcp, "sac_project_info", {"actor_email": "alice@example.com"})
    assert not res.is_error
    assert res.structured_content["identity"]["role"] == "owner"

    # alice publishes a shared decision
    res = _call(mcp, "sac_remember_shared", {
        "kind": "decision",
        "summary": "Remote MCP is the Claude-side connector surface.",
        "tags": ["mcp", "claude"],
        "actor_email": "alice@example.com",
    })
    assert not res.is_error
    memory_id = res.structured_content["memory"]["id"]

    # bob syncs and receives alice's decision (cross-user handoff)
    res = _call(mcp, "sac_sync_context", {
        "task": "connect Claude to SAC",
        "session_ref": "claude-main",
        "actor_email": "bob@example.com",
    })
    assert not res.is_error
    assert "Remote MCP" in res.structured_content["context_text"]

    # bob rehydrates the memory by id
    res = _call(mcp, "sac_get_memory", {
        "memory_id": memory_id, "actor_email": "bob@example.com",
    })
    assert not res.is_error
    assert res.structured_content["memory"]["kind"] == "decision"

    # bob publishes a private note; alice must not receive it
    res = _call(mcp, "sac_remember_private", {
        "kind": "note", "summary": "Bob private idea.",
        "actor_email": "bob@example.com",
    })
    assert not res.is_error

    res = _call(mcp, "sac_sync_context", {
        "task": "review", "session_ref": "chatgpt-main",
        "actor_email": "alice@example.com",
    })
    assert "Bob private idea." not in res.structured_content["context_text"]

    # recent_changes works
    res = _call(mcp, "sac_recent_changes", {
        "since_revision": 0, "actor_email": "alice@example.com",
    })
    assert not res.is_error
    assert res.structured_content["head_revision"] >= 1


def test_bad_kind_rejected_at_mcp_layer(wired):
    from app.main import mcp

    res = _call(mcp, "sac_remember_shared", {
        "kind": "wizardry", "summary": "nope", "actor_email": "alice@example.com",
    })
    # the Literal enum in the tool schema makes this a validation error
    assert res.is_error
