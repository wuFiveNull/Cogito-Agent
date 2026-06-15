from __future__ import annotations

import uuid

from cogito_agent.governance import AuditLogger
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.shared import (
    EventType,
    RuntimeEvent,
    SpanKind,
    TurnState,
    TurnStateMachine,
)
from cogito_agent.storage import Database, MessageRepository, SessionRepository
from cogito_agent.trace import Tracer

from .budget import TurnBudget


class TurnResult:
    def __init__(
        self,
        state: TurnState,
        output: str = "",
        error: str | None = None,
    ) -> None:
        self.state = state
        self.output = output
        self.error = error


class RuntimeKernel:
    def __init__(
        self,
        db: Database,
        budget: TurnBudget | None = None,
        model_adapter: ModelAdapter | None = None,
    ) -> None:
        self._db = db
        self._sm = TurnStateMachine()
        self._tracer = Tracer(db)
        self._audit = AuditLogger(db)
        self._budget = budget or TurnBudget()
        self._model_adapter = model_adapter
        self._sess_repo = SessionRepository(db)
        self._msg_repo = MessageRepository(db)
        self._model_call_count = 0
        self._tool_call_count = 0

    @property
    def state(self) -> TurnState:
        return self._sm.state

    def process(self, event: RuntimeEvent) -> TurnResult:
        trace = self._tracer.create_trace(
            workspace_id=event.workspace_id,
            root_event_id=event.id,
            session_id=event.session_id,
        )
        span = self._tracer.create_span(trace.id, "process_turn", SpanKind.runtime)

        try:
            self._sm.transition(TurnState.loading_session)
            self._sm.transition(TurnState.building_context)
            self._sm.transition(TurnState.awaiting_model)
            self._sm.transition(TurnState.evaluating_result)
            self._sm.transition(TurnState.composing_result)
            output = self._compose_result(event)

            self._sm.transition(TurnState.persisting)
            self._persist(event, output)

            self._sm.transition(TurnState.completed)
            result = TurnResult(state=TurnState.completed, output=output)

        except Exception as exc:
            try:
                self._sm.transition(TurnState.failed)
            except ValueError:
                pass
            error_msg = str(exc)
            result = TurnResult(state=TurnState.failed, error=error_msg)

        self._tracer.end_span(span)
        self._tracer.end_trace(trace)
        return result

    def _compose_result(self, event: RuntimeEvent) -> str:
        if event.type == EventType.user_message:
            raw = event.payload.get("text", "")
            text = str(raw) if raw is not None else ""
            return self._generate_reply(event, text)
        return "I received your request."

    def _generate_reply(self, event: RuntimeEvent, message: str) -> str:
        if not message.strip():
            return "I didn't receive any message."
        if self._model_adapter is None:
            return f"You said: {message}"
        msgs = self._load_context(event, message)
        resp: ModelResponse = self._model_adapter.chat(msgs)
        self._model_call_count += 1
        if resp.error:
            return f"Model error: {resp.error}"
        return resp.content

    def _load_context(
        self, event: RuntimeEvent, message: str
    ) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        recent = self._msg_repo.list_by_session(
            event.workspace_id, event.session_id
        )
        for msg in recent[-6:]:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": message})
        return msgs

    def _persist(self, event: RuntimeEvent, output: str) -> None:
        mid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO messages (id, workspace_id, session_id, role, content)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, event.workspace_id, event.session_id, "assistant", output),
        )
        self._db.connection.commit()
