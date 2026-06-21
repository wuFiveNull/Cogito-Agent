from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.shared import CapabilityManifest, DecisionType, PolicyDecision, PolicyRequest

from .models import CapabilityExecutionRequest, CapabilityExecutionResult


class PolicyEvaluator(Protocol):
    def evaluate(self, request: PolicyRequest) -> PolicyDecision: ...


class ApprovalWriter(Protocol):
    def create(
        self,
        workspace_id: str,
        actor_id: str,
        capability_name: str,
        operation: str = "",
        resource: str = "",
        reason: str = "",
        session_id: str = "",
        tool_call_json: str = "",
    ) -> dict[str, object]: ...


class AuditWriter(Protocol):
    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str = "",
        reason: str = "",
        details: str = "{}",
        redact_details: bool = True,
    ) -> str: ...


class ToolCallTracer(Protocol):
    def log_tool_call(
        self,
        trace_id: str,
        span_id: str,
        capability_name: str,
        input_summary: str = "",
        decision: str = "",
        status: str = "",
        output_summary: str = "",
        latency_ms: int = 0,
        error: str | None = None,
        redactions: list[str] | None = None,
    ) -> None: ...


class CapabilityGuardian(Protocol):
    def inspect(
        self,
        request: CapabilityExecutionRequest,
        manifest: CapabilityManifest,
    ) -> str | None: ...


class ArtifactWriter(Protocol):
    def create_artifact(
        self,
        workspace_id: str,
        source_type: str,
        title: str,
        artifact_type: str = "markdown",
        mime_type: str = "text/markdown",
        content: str = "",
        source_id: str = "",
        created_by: str = "",
        trace_id: str = "",
    ) -> dict[str, object]: ...


class GovernedCapabilityExecutor:
    """The single governed entry point for capability side effects."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        policy: PolicyEvaluator,
        *,
        approvals: ApprovalWriter | None = None,
        audit: AuditWriter | None = None,
        tracer: ToolCallTracer | None = None,
        guardians: list[CapabilityGuardian] | None = None,
        artifact_writer: ArtifactWriter | None = None,
        offload_threshold_chars: int = 4000,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._approvals = approvals
        self._audit = audit
        self._tracer = tracer
        self._guardians = list(guardians or [])
        self._artifact_writer = artifact_writer
        self._offload_threshold = max(1000, offload_threshold_chars)
        self._sleep = sleep

    def execute(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        manifest = self._registry.get_manifest(request.capability_name)
        if manifest is None:
            result = CapabilityExecutionResult(
                status="not_found",
                decision=DecisionType.deny.value,
                reason="Capability not registered",
            )
            self._record(request, result)
            return result

        findings = tuple(
            finding
            for guardian in self._guardians
            if (finding := guardian.inspect(request, manifest)) is not None
        )
        if findings:
            result = CapabilityExecutionResult(
                status="denied",
                decision=DecisionType.deny.value,
                reason="; ".join(findings),
                guardian_findings=findings,
            )
            self._record(request, result)
            return result

        operation = request.operation or manifest.type.value
        resource = request.resource or request.capability_name
        policy_request = PolicyRequest(
            actor_id=request.actor_id,
            capability_name=request.capability_name,
            operation=operation,
            resource=resource,
            context=request.source,
        )
        policy_decision = self._policy.evaluate(policy_request)
        if policy_decision.decision == DecisionType.deny:
            result = CapabilityExecutionResult(
                status="denied",
                decision=policy_decision.decision.value,
                reason=policy_decision.reason,
            )
            self._record(request, result)
            return result

        if policy_decision.decision == DecisionType.require_approval or manifest.approval_required:
            approval_id = self._create_approval(
                request,
                operation=operation,
                resource=resource,
                reason=policy_decision.reason or "Manifest requires approval",
            )
            result = CapabilityExecutionResult(
                status="approval_required",
                decision=DecisionType.require_approval.value,
                reason=policy_decision.reason or "Manifest requires approval",
                approval_id=approval_id,
            )
            self._record(request, result)
            return result

        started_at = datetime.now(UTC)
        tool_result: ToolResult | None = None
        invocation_error: str | None = None
        attempts = 3 if manifest.idempotent else 1
        for attempt in range(attempts):
            try:
                tool_result = self._registry.invoke(
                    request.capability_name,
                    **request.arguments,
                )
                break
            except Exception as exc:
                invocation_error = str(exc)
                if attempt + 1 < attempts:
                    self._sleep(0.1 * (2**attempt))

        latency_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        if tool_result is None:
            tool_result = ToolResult(
                status="error",
                summary="Capability invocation failed",
                error=invocation_error or "Capability returned no result",
            )
        tool_result = self._offload_large_result(request, tool_result)

        status = "ok" if tool_result.status in {"ok", "success"} else "error"
        result = CapabilityExecutionResult(
            status=status,
            decision=policy_decision.decision.value,
            reason=policy_decision.reason,
            tool_result=tool_result,
            latency_ms=latency_ms,
        )
        self._record(request, result)
        return result

    def _offload_large_result(
        self,
        request: CapabilityExecutionRequest,
        tool_result: ToolResult,
    ) -> ToolResult:
        if self._artifact_writer is None:
            return tool_result
        payload = json.dumps(
            {
                "summary": tool_result.summary,
                "error": tool_result.error,
                "data": tool_result.data,
            },
            ensure_ascii=False,
            default=str,
        )
        if len(payload) <= self._offload_threshold:
            return tool_result
        artifact = self._artifact_writer.create_artifact(
            workspace_id=request.workspace_id,
            source_type="tool_result",
            source_id=request.tool_call_id or request.capability_name,
            title=f"Tool output: {request.capability_name}",
            artifact_type="json",
            mime_type="application/json",
            content=payload,
            created_by=request.actor_id,
            trace_id=request.trace_id,
        )
        artifact_id = str(artifact.get("id", ""))
        tool_result.artifacts.append(
            {
                "id": artifact_id,
                "type": "tool_result",
                "mime_type": "application/json",
            }
        )
        prefix = tool_result.summary[:1000]
        tool_result.summary = (
            f"{prefix}\n[Full tool output stored as artifact:{artifact_id}]"
        ).strip()
        if tool_result.error:
            tool_result.error = tool_result.error[:1000]
        return tool_result

    def _create_approval(
        self,
        request: CapabilityExecutionRequest,
        *,
        operation: str,
        resource: str,
        reason: str,
    ) -> str:
        if self._approvals is None:
            return ""
        record = self._approvals.create(
            workspace_id=request.workspace_id,
            actor_id=request.actor_id,
            capability_name=request.capability_name,
            operation=operation,
            resource=resource,
            reason=reason,
            session_id=request.session_id,
            tool_call_json=json.dumps(
                {
                    "capability_name": request.capability_name,
                    "arguments": request.arguments,
                    "tool_call_id": request.tool_call_id,
                }
            ),
        )
        return str(record.get("id", ""))

    def _record(
        self,
        request: CapabilityExecutionRequest,
        result: CapabilityExecutionResult,
    ) -> None:
        tool_result = result.tool_result
        error = tool_result.error if tool_result is not None else None
        summary = tool_result.summary if tool_result is not None else ""
        redactions = list(tool_result.redactions) if tool_result is not None else []
        if self._tracer is not None and request.trace_id:
            self._tracer.log_tool_call(
                trace_id=request.trace_id,
                span_id=request.span_id,
                capability_name=request.capability_name,
                input_summary=str(request.arguments)[:200],
                decision=result.decision,
                status=result.status,
                output_summary=summary[:200],
                latency_ms=result.latency_ms,
                error=error,
                redactions=redactions or None,
            )
        if self._audit is not None:
            self._audit.log(
                actor_id=request.actor_id,
                action="call_tool",
                resource=request.capability_name,
                workspace_id=request.workspace_id,
                session_id=request.session_id,
                trace_id=request.trace_id,
                decision=result.decision,
                reason=result.reason,
                details=json.dumps(
                    {
                        "status": result.status,
                        "source": request.source,
                        "guardian_findings": list(result.guardian_findings),
                    }
                ),
            )
