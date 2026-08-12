"""End-to-end check over real Streamable HTTP MCP.

Seeds two users in one project via a direct store call, then drives the A→B
shared-context handoff through the running HTTP server. Runs against a local
uvicorn in CI (dev mode, actor_email identity) and can target a deployed URL via
SAC_BASE_URL. Once the OAuth layer lands, an authenticated variant supersedes
the dev-mode identity here.
"""
from __future__ import annotations

import asyncio
import os
import time
import urllib.request

from mcp import Client

BASE_URL = os.getenv("SAC_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
MCP_URL = f"{BASE_URL}/mcp"


def wait_for_health(timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - diagnostic retry loop
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"SAC server did not become healthy: {last_error}")


def seed_local() -> None:
    """Seed alice+bob in one project directly in the server's store.

    Only used for the in-process/local run (dev mode). Skipped when targeting a
    remote SAC_BASE_URL, which is expected to be seeded already.
    """
    if os.getenv("SAC_BASE_URL"):
        return
    from app.runtime import get_store

    store = get_store()
    store.init()
    if store.projects.get_user_by_email("alice@example.com"):
        return
    alice = store.projects.create_user("alice@example.com", "Alice")
    bob = store.projects.create_user("bob@example.com", "Bob")
    project = store.projects.create_project("Smoke Project", owner_user_id=alice)
    store.projects.add_membership(project.id, bob, role="member")
    # alice and bob each have exactly one membership, so the server resolves the
    # project automatically — no cross-process SAC_DEFAULT_PROJECT_ID needed.


async def run_mcp_smoke() -> None:
    async with Client(MCP_URL) as client:
        status = await client.call_tool("sac_status", {"actor_email": "alice@example.com"})
        assert not status.is_error, status
        assert status.structured_content is not None

        publish = await client.call_tool(
            "sac_remember_shared",
            {
                "kind": "finding",
                "summary": "HTTP MCP transport successfully published this memory.",
                "tags": ["http", "mcp", "smoke"],
                "importance": 0.9,
                "actor_email": "alice@example.com",
            },
        )
        assert not publish.is_error, publish

        sync = await client.call_tool(
            "sac_sync_context",
            {
                "task": "Verify the remote HTTP MCP shared context handoff",
                "session_ref": "claude-http-smoke",
                "actor_email": "bob@example.com",
            },
        )
        assert not sync.is_error, sync
        assert "HTTP MCP transport successfully published this memory" in str(
            sync.structured_content
        )


if __name__ == "__main__":
    seed_local()
    wait_for_health()
    asyncio.run(run_mcp_smoke())
    print("HTTP MCP smoke test passed")
