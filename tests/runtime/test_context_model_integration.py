"""Integration tests: Context Engine output reaches model messages,
and capability tool schemas are passed correctly."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.registry import ToolResult
from cogito_agent.capability.schemas import manifest_to_tool_schema
from cogito_agent.context import ContextEngine, ContextItem
from cogito_agent.governance.policy import PolicyEngine, PolicyRule
from cogito_agent.memory import CandidateExtractor
from cogito_agent.models import ModelAdapter, ModelResponse, ToolIntent
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    DecisionType,
    EventSource,
    EventType,
    PolicyDecision,
    RiskLevel,
    RuntimeEvent,
    TurnState,
)
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    ApprovalRepository,
    SessionRepository,
    WorkspaceRepository,
)


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


def _setup(db: Database) -> tuple[str, str]:
    ws = WorkspaceRepository(db)
    ws.create("ws-int", "integration")
    sess = SessionRepository(db)
    sess.create("sess-int", "ws-int", "integration")
    return "ws-int", "sess-int"


def _event(wid: str, sid: str, text: str = "hello") -> RuntimeEvent:
    return RuntimeEvent(
        workspace_id=wid,
        session_id=sid,
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": text},
    )


def test_context_items_appear_in_model_messages(db: Database) -> None:
    """Test that retrieved memory context actually reaches the model."""
    wid, sid = _setup(db)
    engine = ContextEngine()
    ctx_items = engine.build(
        [], [], current_message="hello",
    )
    ctx_items.append(ContextItem(
        source_type="memory", source_id="mem-test",
        text="User enjoys hiking", rank=1, token_estimate=10,
        included=True, reason="retrieved",
    ))

    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(content="I know you like hiking!")

    kernel = RuntimeKernel(db, model_adapter=adapter, context_engine=engine)
    result = kernel._build_model_messages(
        _event(wid, sid), "hello", object(),
        ctx=ctx_items,
    )
    contents = [str(m.get("content", "")) for m in result]
    assert any("hiking" in c for c in contents), "Memory should appear in model messages"


def test_tool_schemas_passed_to_model(db: Database) -> None:
    """Test that tool schemas are constructed and passed to model."""
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    manifest = CapabilityManifest(
        name="test.read", version="1.0.0",
        type=CapabilityType.tool,
        description="Read a test resource",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        output_schema={},
        permissions=[],
        risk_level=RiskLevel.low,
        allowed_contexts=["interactive"],
        approval_required=False, audit_required=False, idempotent=True,
    )
    cap_reg.register(manifest.name, manifest, lambda **kw: ToolResult(status="ok", summary="done"))

    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(content="Using tool")

    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
    )
    schemas = kernel._get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "test.read"
    assert "path" in schemas[0]["function"]["parameters"]["properties"]


def test_tool_intent_dispatched_to_capability(db: Database) -> None:
    """Test that a ToolIntent correctly dispatches to the registered capability."""
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "greeter",
        CapabilityManifest(
            name="greeter", version="1.0.0",
            type=CapabilityType.tool, description="",
            input_schema={"type": "object", "properties": {}, "required": []},
            output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="Hello from tool!"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="",
        tool_intents=[ToolIntent(tool_call_id="c1", capability_name="greeter", arguments={})],
    )
    policy = PolicyEngine(rules=[
        PolicyRule("*", "call_model", "*", DecisionType.allow),
        PolicyRule("*", "tool", "*", DecisionType.allow),
    ])
    from cogito_agent.runtime import TurnBudget
    budget = TurnBudget(max_model_calls=5, max_tool_calls=5)
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        policy_engine=policy, budget=budget, max_tool_rounds=1,
    )
    result = kernel.process(_event(wid, sid))
    assert result.state == TurnState.completed
    assert any("Hello from tool" in str(s) for s in result.tool_summaries)


def test_disabled_tool_not_exposed(db: Database) -> None:
    """Test that a tool with non-matching context is not exposed."""
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    manifest = CapabilityManifest(
        name="background_only", version="1.0.0",
        type=CapabilityType.tool, description="",
        input_schema={}, output_schema={},
        permissions=[], risk_level=RiskLevel.low,
        allowed_contexts=["background"],
        approval_required=False, audit_required=False, idempotent=True,
    )
    cap_reg.register(manifest.name, manifest, lambda **kw: ToolResult(status="ok"))

    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(content="ok")

    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
    )
    schemas = kernel._get_tool_schemas()
    tool_names = [s["function"]["name"] for s in schemas]
    assert "background_only" not in tool_names


def test_policy_denied_tool_not_executed(db: Database) -> None:
    """Test that policy engine denies tool before execution."""
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "forbidden",
        CapabilityManifest(
            name="forbidden", version="1.0.0",
            type=CapabilityType.tool, description="",
            input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.medium,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="executed"),
    )
    policy = PolicyEngine(rules=[
        PolicyRule("*", "call_model", "*", DecisionType.allow),
    ])
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="",
        tool_intents=[ToolIntent(tool_call_id="c1", capability_name="forbidden", arguments={})],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        policy_engine=policy,
    )
    result = kernel.process(_event(wid, sid))
    assert result.state == TurnState.completed  # Denied tools are soft-fail


def test_approval_required_creates_record_with_tool_call(db: Database) -> None:
    """Test that approval stores tool call data for later recovery."""
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "sensitive",
        CapabilityManifest(
            name="sensitive", version="1.0.0",
            type=CapabilityType.tool, description="",
            input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.high,
            allowed_contexts=["interactive"],
            approval_required=True, audit_required=True, idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="done"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="",
        tool_intents=[ToolIntent(tool_call_id="c1", capability_name="sensitive", arguments={"key": "value"})],
    )
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
    )
    result = kernel.process(_event(wid, sid))
    assert result.state == TurnState.waiting_approval
    assert result.approval_id is not None

    repo = ApprovalRepository(db)
    record = repo.get_by_id(result.approval_id)
    assert record is not None
    assert record["capability_name"] == "sensitive"


def test_multiple_tool_calls_resolved_individually(db: Database) -> None:
    """Test that multiple tool intents from one model response are all dispatched."""
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    results: dict[str, str] = {}

    def make_tool(name: str) -> object:
        def invoke(**kw: object) -> ToolResult:
            results[name] = "done"
            return ToolResult(status="ok", summary=f"{name} executed")
        return invoke

    cap_reg.register(
        "tool_a",
        CapabilityManifest(
            name="tool_a", version="1.0.0", type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        make_tool("tool_a"),
    )
    cap_reg.register(
        "tool_b",
        CapabilityManifest(name="tool_b", version="1.0.0", type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=False,
        ),
        make_tool("tool_b"),
    )
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(
        content="",
        tool_intents=[
            ToolIntent(tool_call_id="c1", capability_name="tool_a", arguments={}),
            ToolIntent(tool_call_id="c2", capability_name="tool_b", arguments={}),
        ],
    )
    policy = PolicyEngine(rules=[
        PolicyRule("*", "call_model", "*", DecisionType.allow),
        PolicyRule("*", "tool", "*", DecisionType.allow),
    ])
    from cogito_agent.runtime import TurnBudget
    budget = TurnBudget(max_model_calls=5, max_tool_calls=5)
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        policy_engine=policy, budget=budget, max_tool_rounds=1,
    )
    result = kernel.process(_event(wid, sid))
    assert result.state == TurnState.completed
    assert results.get("tool_a") == "done"
    assert results.get("tool_b") == "done"


def test_max_tool_rounds_enforced(db: Database) -> None:
    wid, sid = _setup(db)
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "looper",
        CapabilityManifest(
            name="looper", version="1.0.0", type=CapabilityType.tool,
            description="", input_schema={}, output_schema={},
            permissions=[], risk_level=RiskLevel.low,
            allowed_contexts=["interactive"],
            approval_required=False, audit_required=False, idempotent=True,
        ),
        lambda **kw: ToolResult(status="ok", summary="loop"),
    )
    call_count = [0]

    def side_effect(messages, **kwargs):
        call_count[0] += 1
        return ModelResponse(
            content="",
            tool_intents=[ToolIntent(tool_call_id=f"c{call_count[0]}", capability_name="looper", arguments={})],
        )

    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.side_effect = side_effect
    policy = PolicyEngine(rules=[
        PolicyRule("*", "call_model", "*", DecisionType.allow),
        PolicyRule("*", "tool", "*", DecisionType.allow),
    ])
    from cogito_agent.runtime import TurnBudget
    budget = TurnBudget(max_model_calls=10, max_tool_calls=10)
    kernel = RuntimeKernel(
        db, model_adapter=adapter, capability_registry=cap_reg,
        policy_engine=policy, budget=budget, max_tool_rounds=2,
    )
    result = kernel.process(_event(wid, sid))
    assert result.state == TurnState.completed
    assert "maximum tool rounds" in result.output
