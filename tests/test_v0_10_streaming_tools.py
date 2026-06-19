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
    StreamEvent,
    StreamEventType,
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
    try:
        os.unlink(path)
    except Exception:
        pass


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


def test_stream_no_tools_basic(db: Database) -> None:
    _ensure_ws_and_session(db)
    kernel = RuntimeKernel(db, max_tool_rounds=1)
    events = list(kernel.process_stream(_make_event()))
    types = [e.type for e in events]
    assert StreamEventType.metadata in types
    assert StreamEventType.delta in types
    assert StreamEventType.final in types
    for ev in events:
        if ev.type == StreamEventType.final:
            assert "trace_id" in ev.data
            assert "state" in ev.data


def test_stream_with_tools_dispatched(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "greet",
        CapabilityManifest(
            name="greet", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive", "background"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="Hello!"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="", tool_intents=[{"name": "greet", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        max_tool_rounds=1,
    )
    events = list(kernel.process_stream(_make_event()))
    types = [e.type for e in events]
    assert StreamEventType.tool_call_started in types
    assert StreamEventType.tool_call_completed in types
    assert StreamEventType.final in types


def test_stream_tool_approval_required(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "sensitive_tool",
        CapabilityManifest(
            name="sensitive_tool", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.medium,
            allowed_contexts=["interactive"],
            approval_required=True, audit_required=True, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="done"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="", tool_intents=[{"name": "sensitive_tool", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        max_tool_rounds=1,
    )
    events = list(kernel.process_stream(_make_event()))
    types = [e.type for e in events]
    assert StreamEventType.approval_required in types


def test_stream_tool_policy_deny(db: Database) -> None:
    _ensure_ws_and_session(db)
    from cogito_agent.governance.policy import PolicyEngine, PolicyRule, DecisionType, PolicyRequest
    deny_rule = PolicyRule(
        actor="*", operation="call_tool", context="*",
        decision=DecisionType.deny, capability="write_file",
    )
    allow_call = PolicyRule(
        actor="*", operation="call_model", context="*",
        decision=DecisionType.allow,
    )
    policy = PolicyEngine(rules=[deny_rule, allow_call])
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "write_file",
        CapabilityManifest(
            name="write_file", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.medium,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=True, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="written"),
    )
    # Return tool intents on first call, plain on follow-up
    call_count = [0]

    def _side_effect(messages, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ModelResponse(content="", tool_intents=[{"name": "write_file", "arguments": {}}])
        return ModelResponse(content="done")
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.side_effect = _side_effect
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        policy_engine=policy, max_tool_rounds=1,
    )
    events = list(kernel.process_stream(_make_event()))
    types = [e.type for e in events]
    # Policy deny should not raise (it's handled silently as audit-only)
    assert StreamEventType.final in types


def test_stream_tool_redaction(db: Database) -> None:
    _ensure_ws_and_session(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "reader",
        CapabilityManifest(
            name="reader", version="1.0.0",
            type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="sk-abc123-secret-key"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="", tool_intents=[{"name": "reader", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        max_tool_rounds=1,
    )
    events = list(kernel.process_stream(_make_event()))
    for ev in events:
        if ev.type == StreamEventType.tool_call_completed:
            for tr in ev.data.get("tool_results", []):
                # Summary should be redacted
                assert "sk-" not in str(tr.get("summary", ""))


def test_stream_tool_budget_exceeded(db: Database) -> None:
    _ensure_ws_and_session(db)
    from cogito_agent.runtime.budget import TurnBudget
    budget = TurnBudget(max_tool_calls=0)  # No tool calls allowed
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "expensive",
        CapabilityManifest(
            name="expensive", version="1.0.0",
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
        content="", tool_intents=[{"name": "expensive", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        budget=budget, max_tool_rounds=1,
    )
    events = list(kernel.process_stream(_make_event()))
    types = [e.type for e in events]
    assert StreamEventType.error in types


def test_stream_metadata_contains_trace_id(db: Database) -> None:
    _ensure_ws_and_session(db)
    kernel = RuntimeKernel(db, max_tool_rounds=1)
    events = list(kernel.process_stream(_make_event()))
    meta = [e for e in events if e.type == StreamEventType.metadata]
    assert len(meta) == 1
    assert "trace_id" in meta[0].data
    assert "session_id" in meta[0].data
    assert "workspace_id" in meta[0].data


def test_stream_error_emitted_on_exception(db: Database) -> None:
    _ensure_ws_and_session(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.side_effect = RuntimeError("network error")
    kernel = RuntimeKernel(
        db, model_adapter=adapter, max_tool_rounds=1,
    )
    events = list(kernel.process_stream(_make_event()))
    types = [e.type for e in events]
    assert StreamEventType.error in types
