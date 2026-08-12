import asyncio
import time
import urllib.request

from mcp import Client


BASE_URL = "http://127.0.0.1:8765"


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


async def run_mcp_smoke() -> None:
    async with Client(f"{BASE_URL}/mcp") as client:
        status = await client.call_tool("sac_status", {})
        assert not status.is_error
        assert status.structured_content is not None

        publish = await client.call_tool(
            "sac_publish",
            {
                "actor": "person_a",
                "session_id": "chatgpt-http-smoke",
                "kind": "finding",
                "summary": "HTTP MCP transport successfully published this memory.",
                "tags": ["http", "mcp", "smoke"],
                "importance": 0.9,
            },
        )
        assert not publish.is_error

        sync = await client.call_tool(
            "sac_sync",
            {
                "actor": "person_b",
                "session_id": "claude-http-smoke",
                "task": "Verify the remote HTTP MCP shared context handoff",
                "local_context_delta": "",
                "budget_tokens": 1000,
            },
        )
        assert not sync.is_error
        assert sync.structured_content is not None
        assert "HTTP MCP transport successfully published this memory" in str(
            sync.structured_content
        )


if __name__ == "__main__":
    wait_for_health()
    asyncio.run(run_mcp_smoke())
    print("HTTP MCP smoke test passed")
