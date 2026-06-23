from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from cogito_agent.execution.models import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from cogito_agent.shared import PolicyRequest, Span, SpanKind, Trace


class RuntimePersistencePort(Protocol):
    def list_messages(self, session_id: str, workspace_id: str) -> list[dict[str, object]]: ...

    def get_latest_summary(
        self, workspace_id: str, session_id: str
    ) -> dict[str, object] | None: ...

    def update_summary(self, workspace_id: str, session_id: str) -> dict[str, object] | None: ...

    def trim_messages(
        self, session_id: str, workspace_id: str, keep_count: int
    ) -> int: ...

    def message_count(self, session_id: str, workspace_id: str) -> int: ...

    def persist_interrupted_turn(
        self,
        *,
        event_json: str,
        turn_state: str,
        model_call_count: int,
        tool_call_count: int,
    ) -> None: ...

    def latest_assistant_message_id(self, workspace_id: str, session_id: str) -> str | None: ...

    def persist_user_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        content: str,
        title_if_empty: str,
    ) -> None: ...

    def persist_assistant_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        content: str,
        trace_id: str,
        metadata: dict[str, object] | None = None,
    ) -> None: ...


class RuntimeTracePort(Protocol):
    def create_trace(
        self,
        workspace_id: str,
        root_event_id: str,
        session_id: str | None = None,
    ) -> Trace: ...

    def create_span(
        self,
        trace_id: str,
        name: str,
        kind: SpanKind,
        parent_span_id: str | None = None,
    ) -> Span: ...

    def end_span(self, span: Span, status: str = "completed") -> Span: ...

    def end_trace(self, trace: Trace, status: str = "completed") -> Trace: ...

    def log_model_call(
        self,
        trace_id: str,
        span_id: str,
        provider: str = "",
        model: str = "",
        input_token_count: int = 0,
        output_token_count: int = 0,
        prompt_summary: str = "",
        response_summary: str = "",
        latency_ms: int = 0,
        stop_reason: str = "",
        error: str | None = None,
        redactions: list[str] | None = None,
    ) -> None: ...


class RuntimeAuditPort(Protocol):
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


class RuntimeCapabilityExecutorPort(Protocol):
    def execute(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult: ...


class RuntimePolicyPort(Protocol):
    def evaluate(self, request: PolicyRequest) -> Any: ...


class RuntimeCapabilityCatalogPort(Protocol):
    def list_tools(self) -> list[Any]: ...


class RuntimeArtifactWriterPort(Protocol):
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


class VisionObservationPort(Protocol):
    @property
    def has_vision_capability(self) -> bool: ...

    def set_current_context(self, workspace_id: str, trace_id: str) -> None: ...

    def inspect_image(
        self,
        *,
        attachment_id: str,
        prompt: str,
        workspace_id: str,
        trace_id: str,
    ) -> str: ...

    def require_attachment(self, attachment_id: str, workspace_id: str) -> Any: ...

    def read_attachment_bytes(self, attachment: Any) -> bytes: ...

    def format_observations_for_context(
        self, attachment_ids: list[str], workspace_id: str
    ) -> str: ...


@dataclass(frozen=True)
class RuntimeServices:
    persistence: RuntimePersistencePort
    tracer: RuntimeTracePort
    audit: RuntimeAuditPort
    policy: RuntimePolicyPort
    capability_catalog: RuntimeCapabilityCatalogPort | None = None
    capability_executor: RuntimeCapabilityExecutorPort | None = None


@runtime_checkable
class RuntimeServicesProvider(Protocol):
    """Composition boundary implemented outside ``runtime``."""

    def create_runtime_services(
        self,
        *,
        capability_registry: Any = None,
        policy_engine: Any = None,
        artifact_writer: Any = None,
    ) -> RuntimeServices: ...


class SubagentPersistencePort(Protocol):
    def create_session(
        self,
        session_id: str,
        workspace_id: str,
        title: str,
    ) -> None: ...

    def create_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None: ...


@runtime_checkable
class SubagentPersistenceProvider(Protocol):
    def create_subagent_persistence(self) -> SubagentPersistencePort: ...


class SubagentRuntimeServicesProvider(
    SubagentPersistenceProvider,
    RuntimeServicesProvider,
    Protocol,
):
    @property
    def connection(self) -> Any: ...

    def create_run_repository(self) -> DurableRunPort: ...


class DurableRunPort(Protocol):
    def create(self, **kwargs: Any) -> dict[str, object]: ...
    def claim(self, run_id: str, *, worker_id: str, lease_seconds: int = 300) -> bool: ...
    def set_trace_id(self, run_id: str, trace_id: str) -> None: ...
    def finish(self, run_id: str, **kwargs: Any) -> bool: ...
    def add_output(self, run_id: str, output_type: str, reference_id: str) -> str: ...
    def abandon_expired(self, **kwargs: Any) -> list[dict[str, object]]: ...
    def retry(self, run_id: str) -> bool: ...
    def list_runs(self, **kwargs: Any) -> list[dict[str, object]]: ...


class DurableRunProvider(Protocol):
    def create_run_repository(self) -> DurableRunPort: ...
