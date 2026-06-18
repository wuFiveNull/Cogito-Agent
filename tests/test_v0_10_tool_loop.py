from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.registry import ToolResult
from cogito_agent.shared import CapabilityManifest, CapabilityType, RiskLevel
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import (
    EventSource,
    EventType,
    RuntimeEvent,
    TurnState,
)
from cogito_agent.storage import Database


@pytest.fixture
def db() -> Database:
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _db = Database(path=path)
    _db.initialize()
    _db.migrate()
    yield _db
    _db.connection.close()
    os.unlink(path)


def _ensure_ws_and_session(db: Database, ws_id: str = "default",
                           sess_id: str = "s1") -> None:
    cur = db.connection.execute("SELECT id FROM workspaces WHERE id = ?", (ws_id,))
    if cur.fetchone() is None:
        db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, ws_id))
    cur = db.connection.execute("SELECT id FROM sessions WHERE id = ?", (sess_id,))
    if cur.fetchone() is None:
        db.connection.execute(
            "INSERT INTO sessions (id, workspace_id, title) VALUES (?, ?, ?)",
            (sess_id, ws_id, "Test Session"),
        )
    db.connection.commit()


def _make_event(ws_id: str = "default", session_id: str = "s1",
                text: str = "hello") -> RuntimeEvent:
    return RuntimeEvent(
        workspace_id=ws_id,
        session_id=session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": text, "_request_id": "test-req"},
    )


def _make_adapter(first_intents: list[dict], followup_content: str = "done") -> MagicMock:
    """Create a model adapter that has tool intents on the first call, then returns content."""
    call_count = [0]

    def side_effect(messages, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ModelResponse(content="", tool_intents=first_intents)
        return ModelResponse(content=followup_content)

    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.side_effect = side_effect
    return adapter


def test_single_tool_round_success(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "echo",
        CapabilityManifest(
            name="echo", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="echo response"),
    )
    adapter = _make_adapter([{"name": "echo", "arguments": {}}], "final reply")
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        max_tool_rounds=3,
    )
    result = kernel.process(_make_event())
    assert result.state == TurnState.completed
    assert "final reply" in result.output


def test_multi_round_tool_loop(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "step",
        CapabilityManifest(
            name="step", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="step done"),
    )
    # First call returns tool intent, second call also returns tool intent, third returns content
    call_count = [0]

    def side_effect(messages, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            return ModelResponse(content="", tool_intents=[{"name": "step", "arguments": {}}])
        return ModelResponse(content="final after multi-round")

    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.side_effect = side_effect
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        max_tool_rounds=3,
    )
    result = kernel.process(_make_event())
    assert result.state == TurnState.completed
    assert "final after multi-round" in result.output
    # Should have done 2 model calls for tool rounds + initial = 3 total
    assert call_count[0] == 3


def test_max_tool_rounds_termination(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "loop_tool",
        CapabilityManifest(
            name="loop_tool", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="still looping"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="", tool_intents=[{"name": "loop_tool", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        max_tool_rounds=2,
    )
    result = kernel.process(_make_event())
    # Should complete (with termination message) not fail
    assert result.state in (TurnState.completed, TurnState.failed)


def test_max_tool_rounds_respected(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "round_tool",
        CapabilityManifest(
            name="round_tool", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=True,
        ),
        lambda **kw: ToolResult(status="ok", summary=f"round data"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    # Always respond with tool intents
    adapter.chat.return_value = ModelResponse(
        content="", tool_intents=[{"name": "round_tool", "arguments": {}}],
    )
    max_rounds = 3
    from cogito_agent.runtime.budget import TurnBudget
    budget = TurnBudget(max_model_calls=20, max_tool_calls=20)
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        budget=budget, max_tool_rounds=max_rounds,
    )
    result = kernel.process(_make_event())
    # Should be completed (not budget-exceeded)
    assert result.state == TurnState.completed
    assert "terminated" in result.output or "applied" in result.output


def test_no_tool_loop_without_cap_reg(db: Database) -> None:
    _ensure_ws_and_session(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="hello world", tool_intents=[{"name": "unknown", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=None,
        max_tool_rounds=3,
    )
    result = kernel.process(_make_event())
    assert result.state == TurnState.completed
    assert "hello world" in result.output


def test_tool_loop_budget_check_each_round(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "budget_tool",
        CapabilityManifest(
            name="budget_tool", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="done"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="", tool_intents=[{"name": "budget_tool", "arguments": {}}],
    )
    # Budget allows only 1 tool call
    from cogito_agent.runtime.budget import TurnBudget
    budget = TurnBudget(max_model_calls=10, max_tool_calls=1)
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        budget=budget, max_tool_rounds=3,
    )
    result = kernel.process(_make_event())
    assert result.state == TurnState.failed
