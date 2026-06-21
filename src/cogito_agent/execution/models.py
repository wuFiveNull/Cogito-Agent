from __future__ import annotations

from dataclasses import dataclass, field

from cogito_agent.capability import ToolResult


@dataclass(frozen=True)
class CapabilityExecutionRequest:
    capability_name: str
    arguments: dict[str, object]
    actor_id: str
    source: str
    workspace_id: str
    session_id: str = ""
    trace_id: str = ""
    span_id: str = ""
    operation: str = ""
    resource: str = ""
    tool_call_id: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class CapabilityExecutionResult:
    status: str
    decision: str
    reason: str
    tool_result: ToolResult | None = None
    approval_id: str = ""
    latency_ms: int = 0
    guardian_findings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def succeeded(self) -> bool:
        return self.status == "ok" and self.tool_result is not None
