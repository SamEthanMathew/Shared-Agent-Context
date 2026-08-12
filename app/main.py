from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from .context import compile_context
from .store import SACStore


PROJECT_ID = os.getenv("SAC_PROJECT_ID", "sac-v0")
store = SACStore()

MCP_INSTRUCTIONS = """
Shared Agent Context (SAC) is an always-on shared project memory layer.

For an enabled project chat:
1. At the start of every user turn, call sac_sync BEFORE doing substantive work.
2. On the first turn, local_context_delta may be empty.
3. On later turns, local_context_delta should briefly summarize durable knowledge created
   during the immediately previous turn (findings, decisions, constraints, results, changed
   assumptions). Do not copy the whole transcript.
4. Use the returned shared context as project memory alongside the host model's native chat
   context.
5. Before giving the final answer, call sac_publish for any durable project knowledge that
   another collaborator or agent should know immediately.
6. Do not ask the user whether to sync. Sync automatically while this connector is enabled.

This V0 intentionally treats all published project knowledge as shared.
""".strip()

mcp = MCPServer(
    "Shared Agent Context V0",
    instructions=MCP_INSTRUCTIONS,
)

# V0 is intentionally unauthenticated and publicly reachable for a two-account proof.
# DNS-rebinding protection is disabled because the deployment hostname is assigned by the host.
# Replace this with strict host allowlists + OAuth before any real multi-user use.
transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)

# MCP SDK v2 moved transport/runtime configuration out of the server constructor.
# streamable_http_path="/" makes the mounted endpoint exactly /mcp instead of /mcp/mcp.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    transport_security=transport_security,
)


class SyncRequest(BaseModel):
    actor: str = Field(..., description="Stable collaborator label, e.g. person_a or person_b.")
    session_id: str = Field(..., description="Stable label for this chat/workstream.")
    task: str = Field(..., description="The current user request or task.")
    local_context_delta: str = Field(
        default="",
        description=(
            "Concise durable knowledge created in the immediately previous local turn. "
            "Leave empty on the first turn."
        ),
    )
    budget_tokens: int = Field(
        default=3000,
        ge=500,
        le=20000,
        description="Approximate SAC context budget for this model/turn.",
    )


class PublishRequest(BaseModel):
    actor: str
    session_id: str
    kind: Literal[
        "decision",
        "requirement",
        "constraint",
        "finding",
        "result",
        "observation",
        "task",
        "note",
    ] = "finding"
    summary: str = Field(..., min_length=1)
    details: str = ""
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.6, ge=0.0, le=1.0)


def sync_impl(
    actor: str,
    session_id: str,
    task: str,
    local_context_delta: str = "",
    budget_tokens: int = 3000,
) -> dict:
    actor = actor.strip()
    session_id = session_id.strip()
    task = task.strip()
    if not actor or not session_id or not task:
        raise ValueError("actor, session_id, and task are required")

    if local_context_delta.strip():
        store.add_memory(
            project_id=PROJECT_ID,
            actor=actor,
            session_id=session_id,
            kind="session_delta",
            summary=local_context_delta.strip(),
            importance=0.55,
        )

    result = compile_context(
        store=store,
        project_id=PROJECT_ID,
        task=task,
        actor=actor,
        session_id=session_id,
        budget_tokens=budget_tokens,
    )
    store.update_session(
        project_id=PROJECT_ID,
        actor=actor,
        session_id=session_id,
        revision=result["revision"],
        task=task,
    )
    return result


def publish_impl(
    actor: str,
    session_id: str,
    kind: str,
    summary: str,
    details: str = "",
    tags: list[str] | None = None,
    importance: float = 0.6,
) -> dict:
    memory = store.add_memory(
        project_id=PROJECT_ID,
        actor=actor.strip(),
        session_id=session_id.strip(),
        kind=kind,
        summary=summary,
        details=details,
        tags=tags,
        importance=importance,
    )
    return {
        "ok": True,
        "project_id": PROJECT_ID,
        "revision": memory.revision,
        "memory": memory.as_dict(include_details=True),
    }


@mcp.tool()
def sac_sync(
    actor: str,
    session_id: str,
    task: str,
    local_context_delta: str = "",
    budget_tokens: int = 3000,
) -> dict:
    """
    MUST be called automatically at the start of every turn while SAC is enabled.

    It optionally writes the previous local turn's durable delta, then returns the
    task-relevant shared project context plus changes since this session last synced.
    """
    return sync_impl(
        actor=actor,
        session_id=session_id,
        task=task,
        local_context_delta=local_context_delta,
        budget_tokens=budget_tokens,
    )


@mcp.tool()
def sac_publish(
    actor: str,
    session_id: str,
    kind: str,
    summary: str,
    details: str = "",
    tags: list[str] | None = None,
    importance: float = 0.6,
) -> dict:
    """
    Publish durable knowledge to the shared SAC immediately.

    Call before the final answer whenever this turn produced a reusable decision,
    requirement, constraint, finding, result, or other project-relevant fact.
    """
    return publish_impl(
        actor=actor,
        session_id=session_id,
        kind=kind,
        summary=summary,
        details=details,
        tags=tags,
        importance=importance,
    )


@mcp.tool()
def sac_get_memory(memory_id: str) -> dict:
    """Rehydrate one shared memory item when the compact sync context lacks detail."""
    memory = store.get_memory(PROJECT_ID, memory_id)
    if memory is None:
        return {"ok": False, "error": "memory_not_found", "memory_id": memory_id}
    return {"ok": True, "memory": memory.as_dict(include_details=True)}


@mcp.tool()
def sac_status() -> dict:
    """Return current V0 shared-context status."""
    return {
        "project_id": PROJECT_ID,
        "revision": store.current_revision(PROJECT_ID),
        "memory_count": store.count_memories(PROJECT_ID),
        "mode": "v0_single_shared_pool_no_auth",
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Shared Agent Context V0",
    version="0.1.0",
    description=(
        "Minimal shared-context service. Claude connects through MCP at /mcp; "
        "ChatGPT Custom GPT Actions can use the REST endpoints/OpenAPI schema."
    ),
    lifespan=lifespan,
)


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {
        "ok": True,
        "project_id": PROJECT_ID,
        "revision": store.current_revision(PROJECT_ID),
    }


@app.get("/api/status", operation_id="sac_status")
def api_status() -> dict:
    return {
        "project_id": PROJECT_ID,
        "revision": store.current_revision(PROJECT_ID),
        "memory_count": store.count_memories(PROJECT_ID),
        "mode": "v0_single_shared_pool_no_auth",
    }


@app.post("/api/sync", operation_id="sac_sync_context")
def api_sync(payload: SyncRequest) -> dict:
    try:
        return sync_impl(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/publish", operation_id="sac_publish_context")
def api_publish(payload: PublishRequest) -> dict:
    try:
        return publish_impl(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/memory/{memory_id}", operation_id="sac_get_memory")
def api_get_memory(memory_id: str) -> dict:
    memory = store.get_memory(PROJECT_ID, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"ok": True, "memory": memory.as_dict(include_details=True)}


# The MCP protocol endpoint is exactly /mcp.
app.mount("/mcp", mcp_app)
