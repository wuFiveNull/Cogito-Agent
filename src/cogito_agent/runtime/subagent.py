from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MessageRepository, SessionRepository

from .drift import DriftRuntime
from .kernel import TurnResult


class SubagentSession:
    def __init__(
        self,
        id: str,
        parent_session_id: str,
        workspace_id: str,
        name: str = "",
        instruction: str = "",
    ) -> None:
        self.id = id
        self.parent_session_id = parent_session_id
        self.workspace_id = workspace_id
        self.name = name
        self.instruction = instruction
        self.status: str = "created"
        self.result: TurnResult | None = None
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
    ) -> SubagentSession:
        sid = str(uuid.uuid4())
        sub = SubagentSession(
            id=sid,
            parent_session_id=parent_session_id,
            workspace_id=workspace_id,
            name=name,
            instruction=instruction,
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
            payload={"text": text},
        )

        task_id = self._drift.submit(event, timeout=timeout)
        result = self._drift.get_result(task_id)
        sub.result = result
        sub.status = "completed" if result and result.error is None else "failed"
        sub.completed_at = datetime.now(UTC).isoformat()
        return result

    def merge(self, subagent_id: str) -> TurnResult | None:
        sub = self._subagents.get(subagent_id)
        if sub is None or sub.result is None:
            return None
        sub_msgs = self._msg_repo.list_by_session(
            sub.id, sub.workspace_id
        )

        for msg in sub_msgs:
            self._msg_repo.create(
                mid=str(uuid.uuid4()),
                workspace_id=sub.workspace_id,
                session_id=sub.parent_session_id,
                role=str(msg.get("role", "assistant")),
                content=str(msg.get("content", "")),
            )

        sub.status = "merged"
        return sub.result

    def get(self, subagent_id: str) -> SubagentSession | None:
        return self._subagents.get(subagent_id)

    def list_by_parent(self, parent_session_id: str) -> list[SubagentSession]:
        return [
            s for s in self._subagents.values()
            if s.parent_session_id == parent_session_id
        ]
