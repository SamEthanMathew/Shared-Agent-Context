from pathlib import Path

from app.context import compile_context
from app.store import SACStore


def test_shared_context_round_trip(tmp_path: Path):
    store = SACStore(f"sqlite:///{tmp_path / 'sac.db'}")
    store.init()

    first = store.add_memory(
        project_id="test-project",
        actor="person_a",
        session_id="chatgpt-main",
        kind="decision",
        summary="Use PostgreSQL for durable shared context.",
        tags=["database", "architecture"],
        importance=0.9,
    )

    assert first.revision == 1
    assert store.current_revision("test-project") == 1

    compiled = compile_context(
        store=store,
        project_id="test-project",
        task="Design the database persistence layer",
        actor="person_b",
        session_id="claude-main",
        budget_tokens=1000,
    )

    assert compiled["revision"] == 1
    assert "PostgreSQL" in compiled["context_text"]
    assert "person_a" in compiled["context_text"]

    store.update_session(
        project_id="test-project",
        actor="person_b",
        session_id="claude-main",
        revision=1,
        task="Design the database persistence layer",
    )

    store.add_memory(
        project_id="test-project",
        actor="person_a",
        session_id="chatgpt-main",
        kind="finding",
        summary="Remote MCP is the Claude-side connector surface.",
        tags=["mcp", "claude"],
    )

    compiled_again = compile_context(
        store=store,
        project_id="test-project",
        task="Connect Claude to SAC",
        actor="person_b",
        session_id="claude-main",
        budget_tokens=1000,
    )

    assert compiled_again["previous_session_revision"] == 1
    assert compiled_again["revision"] == 2
    assert "Remote MCP" in compiled_again["context_text"]


def test_service_imports():
    from app.main import app, mcp

    assert app.title == "Shared Agent Context V0"
    assert mcp is not None
    assert any(getattr(route, "path", None) == "/mcp" for route in app.routes)
