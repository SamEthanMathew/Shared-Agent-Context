"""The four context-management tools, and how the surface behaves when no
context can be resolved."""
from __future__ import annotations

import asyncio


def _call(tool, args):
    from mcp import Client

    from app.main import mcp

    async def run():
        async with Client(mcp) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(run()).structured_content


ALICE = {"actor_email": "alice@example.com"}
BOB = {"actor_email": "bob@example.com"}


def test_list_contexts_shows_membership_and_active(wired):
    out = _call("sac_list_contexts", ALICE)
    assert out["ok"] is True
    assert out["count"] == 1
    c = out["contexts"][0]
    assert c["name"] == "Shared Desktop App"
    assert c["access"] == "owner"
    assert c["is_active"] is True  # sole membership resolves as active


def test_list_contexts_is_per_user(wired):
    # bob sees the shared context as "edit"; carol's project is invisible
    out = _call("sac_list_contexts", BOB)
    assert [c["access"] for c in out["contexts"]] == ["edit"]
    assert all(c["name"] != "Carol Solo Project" for c in out["contexts"])


def test_create_context_makes_it_active(wired):
    out = _call("sac_create_context", {"name": "Launch Plan", **ALICE})
    assert out["ok"] is True
    assert out["active_context"]["name"] == "Launch Plan"
    assert out["active_context"]["slug"] == "launch-plan"
    assert out["active_context"]["access"] == "owner"

    # subsequent calls with no explicit context land in the new one
    info = _call("sac_context_info", ALICE)
    assert info["active_context"]["name"] == "Launch Plan"


def test_use_context_switches_by_name(wired):
    _call("sac_create_context", {"name": "Launch Plan", **ALICE})
    out = _call("sac_use_context", {"context": "Shared Desktop App", **ALICE})
    assert out["switched"] is True
    assert out["active_context"]["name"] == "Shared Desktop App"
    assert "Now working in 'Shared Desktop App'" in out["message"]
    assert _call("sac_context_info", ALICE)["active_context"]["name"] == "Shared Desktop App"


def test_use_context_chat_scope_does_not_move_the_client(wired):
    _call("sac_create_context", {"name": "Launch Plan", **ALICE})  # active
    out = _call("sac_use_context", {
        "context": "Shared Desktop App", "scope": "chat",
        "session_ref": "chat-a", **ALICE,
    })
    assert out["scope"] == "chat"
    # the client default is still the newly created context
    assert _call("sac_context_info", ALICE)["active_context"]["name"] == "Launch Plan"


def test_use_context_refuses_other_tenants(wired):
    out = _call("sac_use_context", {"context": "Carol Solo Project", **ALICE})
    assert out["ok"] is False
    assert out["error"] == "ForbiddenError"


def test_needs_context_selection_is_actionable(wired):
    # two contexts, no binding -> the agent gets a list, not a dead error
    _call("sac_create_context", {"name": "Launch Plan", **ALICE})
    wired.store.projects.clear_bindings_for_project(wired.project_id)
    from app.db import context_bindings
    with wired.store.engine.begin() as conn:
        from sqlalchemy import delete
        conn.execute(delete(context_bindings))

    out = _call("sac_status", ALICE)
    assert out["ok"] is False
    assert out["error"] == "needs_context_selection"
    names = {c["name"] for c in out["contexts"]}
    assert names == {"Shared Desktop App", "Launch Plan"}
    assert "sac_use_context" in out["hint"]


def test_needs_context_selection_when_user_has_none(wired):
    wired.store.projects.create_user("solo@example.com", "Solo")
    out = _call("sac_status", {"actor_email": "solo@example.com"})
    assert out["ok"] is False
    assert out["error"] == "needs_context_selection"
    assert out["contexts"] == []
    assert "sac_create_context" in out["hint"]


def test_every_response_carries_active_context(wired):
    for tool, args in [
        ("sac_status", ALICE),
        ("sac_project_info", ALICE),
        ("sac_context_info", ALICE),
        ("sac_recent_changes", {"since_revision": 0, **ALICE}),
        ("sac_sync_context", {"task": "anything", **ALICE}),
    ]:
        out = _call(tool, args)
        assert out.get("active_context"), f"{tool} did not report active_context"
        assert out["active_context"]["name"] == "Shared Desktop App"


def test_context_param_targets_another_context_for_one_call(wired):
    _call("sac_create_context", {"name": "Launch Plan", **ALICE})  # now active
    # write into the *other* context without switching
    out = _call("sac_remember_shared", {
        "kind": "decision", "summary": "Targeted write.",
        "context": "Shared Desktop App", **ALICE,
    })
    assert out["ok"] is True
    assert out["active_context"]["name"] == "Shared Desktop App"
    # the client default is unchanged
    assert _call("sac_context_info", ALICE)["active_context"]["name"] == "Launch Plan"


def test_deprecated_project_id_param_still_works(wired):
    out = _call("sac_status", {"project_id": wired.project_id, **ALICE})
    assert out["ok"] is True
    assert out["active_context"]["id"] == wired.project_id


def test_cross_context_isolation_of_memory(wired):
    """Memory must not bleed between contexts."""
    _call("sac_remember_shared", {
        "kind": "decision", "summary": "Belongs to Desktop App.", **ALICE})
    _call("sac_create_context", {"name": "Launch Plan", **ALICE})
    out = _call("sac_sync_context", {"task": "what do we know", **ALICE})
    assert out["active_context"]["name"] == "Launch Plan"
    assert "Belongs to Desktop App" not in out["context_text"]


def test_context_info_reports_capabilities(wired):
    alice = _call("sac_context_info", ALICE)
    assert alice["can_write"] is True and alice["can_share"] is True
    bob = _call("sac_context_info", BOB)
    assert bob["can_write"] is True and bob["can_share"] is False
