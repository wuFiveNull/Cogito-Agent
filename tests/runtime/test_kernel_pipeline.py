from __future__ import annotations

from unittest.mock import MagicMock

from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.memory import MemoryRetriever
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.runtime import TurnBudget
from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    DecisionType,
    EventSource,
    EventType,
    RiskLevel,
    RuntimeEvent,
    TurnState,
)
from cogito_agent.storage import (
    Database,
    SessionRepository,
    WorkspaceRepository,
)


def _setup(db: Database) -> None:
    ws = WorkspaceRepository(db)
    ws.create("ws-1", "test")
    sess = SessionRepository(db)
    sess.create("sess-1", "ws-1", "test")


def _make_event(text: str = "hello") -> RuntimeEvent:
    return RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": text},
    )


def test_budget_exceeded_model_call(db: Database) -> None:
    _setup(db)
    budget = TurnBudget(max_model_calls=0)
    kernel = RuntimeKernel(db, budget=budget)
    result = kernel.process(_make_event())
    assert result.state == TurnState.failed
    assert "budget" in (result.error or "").lower()


def test_budget_exceeded_tool_call(db: Database) -> None:
    _setup(db)
    budget = TurnBudget(max_tool_calls=0)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "test_tool",
        CapabilityManifest(
            name="test_tool",
            version="1.0.0",
            type=CapabilityType.tool,
            description="",
            input_schema={},
            output_schema={},
            permissions=[],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive", "background"],
            approval_required=False,
            audit_required=False,
            idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="done"),
    )
    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="using tool",
        tool_intents=[{"name": "test_tool", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db,
        budget=budget,
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
    )
    result = kernel.process(_make_event())
    assert result.state == TurnState.failed
    assert "budget" in (result.error or "").lower()


def test_policy_denied_model_call(db: Database) -> None:
    from cogito_agent.governance import PolicyEngine
    from cogito_agent.shared import PolicyDecision

    _setup(db)
    policy = PolicyEngine(rules=[])
    policy.evaluate = MagicMock(
        return_value=PolicyDecision(decision=DecisionType.deny, reason="test deny")
    )
    kernel = RuntimeKernel(db, policy_engine=policy)
    result = kernel.process(_make_event())
    assert result.state == TurnState.denied
    assert "denied" in (result.error or "").lower()


def test_pipeline_success_with_memory_retrieval(db: Database) -> None:
    _setup(db)
    mem_retriever = MemoryRetriever(db)
    kernel = RuntimeKernel(db, memory_retriever=mem_retriever)
    result = kernel.process(_make_event("hello"))
    assert result.state == TurnState.completed
    assert result.output == "You said: hello"


def test_pipeline_tool_result_summaries(db: Database) -> None:
    _setup(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "greet",
        CapabilityManifest(
            name="greet",
            version="1.0.0",
            type=CapabilityType.tool,
            description="",
            input_schema={},
            output_schema={},
            permissions=[],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive", "background"],
            approval_required=False,
            audit_required=False,
            idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="Hello, world!"),
    )
    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="Let me greet you",
        tool_intents=[{"name": "greet", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db,
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
        max_tool_rounds=1,
    )
    result = kernel.process(_make_event("hi"))
    assert result.state == TurnState.completed
    assert len(result.tool_summaries) >= 1
    assert result.tool_summaries[0]["tool"] == "greet"
    assert result.tool_summaries[0]["summary"] == "Hello, world!"


def test_pipeline_tool_not_found(db: Database) -> None:
    _setup(db)
    cap_reg = CapabilityRegistry()
    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="unknown tool",
        tool_intents=[{"name": "nonexistent_tool", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db,
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
    )
    result = kernel.process(_make_event("run tool"))
    assert result.state == TurnState.completed


def test_pipeline_approval_required(db: Database) -> None:
    _setup(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "write_file",
        CapabilityManifest(
            name="write_file",
            version="1.0.0",
            type=CapabilityType.tool,
            description="",
            input_schema={},
            output_schema={},
            permissions=[],
            risk_level=RiskLevel.medium,
            allowed_contexts=["interactive"],
            approval_required=True,
            audit_required=True,
            idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="written"),
    )
    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="writing file",
        tool_intents=[{"name": "write_file", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db,
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
    )
    result = kernel.process(_make_event("write a file"))
    assert result.state == TurnState.waiting_approval
    assert result.approval_pending
    assert result.approval_id is not None


def test_pipeline_model_call_logging(db: Database) -> None:
    _setup(db)
    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="response",
        model="gpt-4",
        provider="openai",
        input_tokens=10,
        output_tokens=20,
        latency_ms=100,
        stop_reason="stop",
    )
    kernel = RuntimeKernel(db, model_adapter=mock_adapter)
    result = kernel.process(_make_event("log test"))
    assert result.state == TurnState.completed
    cur = db.connection.execute(
        "SELECT * FROM model_calls WHERE model = ?",
        ("gpt-4",),
    )
    rows = cur.fetchall()
    assert len(rows) >= 1


def test_pipeline_audit_log(db: Database) -> None:
    _setup(db)
    kernel = RuntimeKernel(db)
    result = kernel.process(_make_event("audit test"))
    assert result.state == TurnState.completed
    cur = db.connection.execute(
        "SELECT * FROM audit_logs WHERE action = ?",
        ("turn_completed",),
    )
    rows = cur.fetchall()
    assert len(rows) >= 1


def test_pipeline_sources_in_result(db: Database) -> None:
    _setup(db)
    kernel = RuntimeKernel(db)
    result = kernel.process(_make_event("source test"))
    assert result.state == TurnState.completed
    assert len(result.sources) >= 1
    assert any(s.get("type") == "current_message" for s in result.sources)


def test_tool_retry_on_failure(db: Database) -> None:
    _setup(db)
    call_count = [0]

    def flaky_invoke(**kwargs: object) -> ToolResult:
        call_count[0] += 1
        if call_count[0] < 3:
            raise RuntimeError("transient failure")
        return ToolResult(status="ok", summary="success on retry")

    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "flaky_tool",
        CapabilityManifest(
            name="flaky_tool",
            version="1.0.0",
            type=CapabilityType.tool,
            description="",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={"type": "object"},
            permissions=[],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False,
            audit_required=False,
            idempotent=True,
        ),
        flaky_invoke,
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="",
        tool_intents=[{"name": "flaky_tool", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db,
        model_adapter=adapter,
        capability_registry=cap_reg,
        max_tool_rounds=1,
    )
    result = kernel.process(_make_event())
    # Should succeed after retry
    assert result.state == TurnState.completed


def test_tool_retry_not_idempotent_skipped(db: Database) -> None:
    _setup(db)
    call_count = [0]

    def flaky_invoke(**kwargs: object) -> ToolResult:
        call_count[0] += 1
        raise RuntimeError("always fails")

    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "non_idempotent_tool",
        CapabilityManifest(
            name="non_idempotent_tool",
            version="1.0.0",
            type=CapabilityType.tool,
            description="",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={"type": "object"},
            permissions=[],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False,
            audit_required=False,
            idempotent=False,
        ),
        flaky_invoke,
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="",
        tool_intents=[{"name": "non_idempotent_tool", "arguments": {}}],
    )
    kernel = RuntimeKernel(
        db,
        model_adapter=adapter,
        capability_registry=cap_reg,
    )
    result = kernel.process(_make_event())
    # Should fail without retry (only 1 attempt since not idempotent)
    assert result.state == TurnState.failed
    assert call_count[0] == 1
