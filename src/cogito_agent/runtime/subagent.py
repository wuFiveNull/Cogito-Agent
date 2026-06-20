from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.models.messages import ContentPart, TextPart
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MessageRepository, SessionRepository

from .drift import DriftRuntime
from .kernel import TurnResult


class SubagentProfile:
    """Defines the capabilities and constraints of a subagent."""

    def __init__(
        self,
        name: str,
        role: str = "executor",
        system_instruction: str = "",
        required_capabilities: frozenset[str] | None = None,
        preferred_candidates: tuple[str, ...] = (),
        allowed_tools: frozenset[str] | None = None,
        output_schema: dict[str, object] | None = None,
        max_model_calls: int = 4,
        max_tool_calls: int = 2,
        max_cost_usd: float = 0.0,
    ) -> None:
        self.name = name
        self.role = role
        self.system_instruction = system_instruction
        self.required_capabilities = required_capabilities or frozenset({"chat"})
        self.preferred_candidates = preferred_candidates
        self.allowed_tools = allowed_tools or frozenset()
        self.output_schema = output_schema
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.max_cost_usd = max_cost_usd


class SubagentResult:
    """Structured result from a subagent, NOT a full message history copy."""

    def __init__(
        self,
        status: str = "completed",
        summary: str = "",
        structured_output: dict[str, object] | None = None,
        artifact_refs: list[str] | None = None,
        trace_id: str = "",
        model_candidate_id: str = "",
        confidence: float | None = None,
        error: str = "",
    ) -> None:
        self.status = status
        self.summary = summary
        self.structured_output = structured_output
        self.artifact_refs = artifact_refs or []
        self.trace_id = trace_id
        self.model_candidate_id = model_candidate_id
        self.confidence = confidence
        self.error = error

    def is_ok(self) -> bool:
        return self.status == "completed" and not self.error

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "structured_output": self.structured_output,
            "artifact_refs": self.artifact_refs,
            "trace_id": self.trace_id,
            "model_candidate_id": self.model_candidate_id,
            "confidence": self.confidence,
            "error": self.error,
        }


class SubagentSession:
    def __init__(
        self,
        id: str,
        parent_session_id: str,
        workspace_id: str,
        name: str = "",
        instruction: str = "",
        profile: SubagentProfile | None = None,
    ) -> None:
        self.id = id
        self.parent_session_id = parent_session_id
        self.workspace_id = workspace_id
        self.name = name
        self.instruction = instruction
        self.profile = profile
        self.status: str = "created"
        self.result: TurnResult | None = None
        self.subagent_result: SubagentResult | None = None
        self.created_at = datetime.now(UTC).isoformat()
        self.completed_at: str | None = None


class SubagentManager:
    def __init__(
        self,
        db: Database,
        drift_runtime: DriftRuntime | None = None,
        kernel_factory: Any = None,
    ) -> None:
        self._db = db
        self._drift = drift_runtime or DriftRuntime(
            db, kernel_factory=kernel_factory
        )
        self._sess_repo = SessionRepository(db)
        self._msg_repo = MessageRepository(db)
        self._subagents: dict[str, SubagentSession] = {}

    def fork(
        self,
        parent_session_id: str,
        workspace_id: str,
        name: str = "",
        instruction: str = "",
        initial_message: str = "",
        profile: SubagentProfile | None = None,
        content: list[ContentPart] | None = None,
    ) -> SubagentSession:
        sid = str(uuid.uuid4())
        sub = SubagentSession(
            id=sid,
            parent_session_id=parent_session_id,
            workspace_id=workspace_id,
            name=name,
            instruction=instruction,
            profile=profile,
        )

        self._sess_repo.create(sid, workspace_id, f"sub:{name}" if name else "subagent")

        if instruction:
            self._msg_repo.create(
                mid=str(uuid.uuid4()),
                workspace_id=workspace_id,
                session_id=sid,
                role="system",
                content=instruction,
            )

        if initial_message:
            self._msg_repo.create(
                mid=str(uuid.uuid4()),
                workspace_id=workspace_id,
                session_id=sid,
                role="user",
                content=initial_message,
            )

        if content:
            text_parts = [p for p in content if isinstance(p, TextPart)]
            if text_parts:
                combined = "\n".join(p.text for p in text_parts)
                self._msg_repo.create(
                    mid=str(uuid.uuid4()),
                    workspace_id=workspace_id,
                    session_id=sid,
                    role="user",
                    content=combined,
                )

        self._subagents[sid] = sub
        return sub

    def run(
        self,
        subagent_id: str,
        message: str = "",
        timeout: float | None = None,
    ) -> TurnResult | None:
        sub = self._subagents.get(subagent_id)
        if sub is None:
            return None

        sub.status = "running"

        text = message or sub.instruction or "Please proceed."
        event = RuntimeEvent(
            workspace_id=sub.workspace_id,
            session_id=sub.id,
            actor_id="system",
            source=EventSource.api,
            type=EventType.user_message,
            payload={
                "text": text,
                "_subagent_role": sub.profile.role if sub.profile else "",
            },
        )

        task_id = self._drift.submit(event, timeout=timeout)
        result = self._drift.get_result(task_id)
        sub.result = result
        sub.status = "completed" if result and result.error is None else "failed"
        sub.completed_at = datetime.now(UTC).isoformat()

        sub.subagent_result = SubagentResult(
            status=sub.status,
            summary=result.output if result else "",
            trace_id=result.trace_id if result else "",
            error=result.error if result else "",
            confidence=0.5,
        )

        return result

    def merge(self, subagent_id: str) -> TurnResult | None:
        """Merge subagent results back to parent.

        This version does NOT copy full message history.
        Instead, it returns a SubagentResult that parent can consume.
        """
        sub = self._subagents.get(subagent_id)
        if sub is None or sub.result is None:
            return None

        result_text = sub.result.output or ""
        if result_text:
            self._msg_repo.create(
                mid=str(uuid.uuid4()),
                workspace_id=sub.workspace_id,
                session_id=sub.parent_session_id,
                role="assistant",
                content=(
                    f"[Subagent: {sub.name or sub.id}]\n{result_text}"
                ),
            )

        sub.status = "merged"
        return sub.result

    def get_result(self, subagent_id: str) -> SubagentResult | None:
        sub = self._subagents.get(subagent_id)
        if sub is None:
            return None
        return sub.subagent_result

    def get(self, subagent_id: str) -> SubagentSession | None:
        return self._subagents.get(subagent_id)

    def list_by_parent(self, parent_session_id: str) -> list[SubagentSession]:
        return [
            s for s in self._subagents.values()
            if s.parent_session_id == parent_session_id
        ]
