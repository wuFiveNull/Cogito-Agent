from __future__ import annotations

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.execution import CapabilityExecutionRequest, GovernedCapabilityExecutor
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.shared import CapabilityManifest, CapabilityType, DecisionType, RiskLevel


def _manifest(*, approval_required: bool = False, idempotent: bool = False) -> CapabilityManifest:
    return CapabilityManifest(
        name="test.tool",
        version="1.0.0",
        type=CapabilityType.tool,
        description="test",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permissions=[],
        risk_level=RiskLevel.low,
        allowed_contexts=["interactive"],
        approval_required=approval_required,
        audit_required=True,
        idempotent=idempotent,
    )


def _request() -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability_name="test.tool",
        arguments={"value": "ok"},
        actor_id="assistant",
        source="interactive",
        workspace_id="workspace",
        session_id="session",
    )


def test_missing_capability_is_denied() -> None:
    executor = GovernedCapabilityExecutor(CapabilityRegistry(), PolicyEngine())
    result = executor.execute(_request())
    assert result.status == "not_found"
    assert result.decision == "deny"


def test_policy_denial_prevents_invocation() -> None:
    called = False

    def invoke(**kwargs: object) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(summary=str(kwargs))

    registry = CapabilityRegistry()
    registry.register("test.tool", _manifest(), invoke)
    policy = PolicyEngine(
        [
            PolicyRule("*", "tool", "interactive", DecisionType.deny),
        ]
    )
    result = GovernedCapabilityExecutor(registry, policy).execute(_request())
    assert result.status == "denied"
    assert called is False


def test_manifest_approval_stops_before_invocation() -> None:
    called = False

    def invoke(**kwargs: object) -> ToolResult:
        nonlocal called
        called = True
        return ToolResult(summary=str(kwargs))

    registry = CapabilityRegistry()
    registry.register("test.tool", _manifest(approval_required=True), invoke)
    result = GovernedCapabilityExecutor(registry, PolicyEngine()).execute(_request())
    assert result.status == "approval_required"
    assert called is False


def test_idempotent_capability_retries() -> None:
    calls = 0

    def invoke(**kwargs: object) -> ToolResult:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("temporary")
        return ToolResult(summary=str(kwargs["value"]))

    registry = CapabilityRegistry()
    registry.register("test.tool", _manifest(idempotent=True), invoke)
    result = GovernedCapabilityExecutor(
        registry,
        PolicyEngine(),
        sleep=lambda _: None,
    ).execute(_request())
    assert result.succeeded
    assert calls == 3


def test_large_tool_result_is_offloaded() -> None:
    class ArtifactWriter:
        def __init__(self) -> None:
            self.content = ""

        def create_artifact(self, **kwargs: object) -> dict[str, object]:
            self.content = str(kwargs["content"])
            return {"id": "artifact-1"}

    registry = CapabilityRegistry()
    registry.register(
        "test.tool",
        _manifest(),
        lambda **_: ToolResult(summary="x" * 5000),
    )
    writer = ArtifactWriter()
    result = GovernedCapabilityExecutor(
        registry,
        PolicyEngine(),
        artifact_writer=writer,  # type: ignore[arg-type]
        offload_threshold_chars=1000,
    ).execute(_request())
    assert result.succeeded
    assert result.tool_result is not None
    assert "artifact:artifact-1" in result.tool_result.summary
    assert result.tool_result.artifacts[0]["id"] == "artifact-1"
    assert len(writer.content) > 4000
