from __future__ import annotations

from cogito_agent.storage.database import Database
from cogito_agent.storage.session_store import SessionStore


class SqliteRuntimePersistence:
    """SQLite adapter for RuntimeKernel's persistence port.

    Delegates to ``SessionStore`` for all message and session operations.
    This indirection lets the message layer (MessageQueue, AgentLoop) and
    the kernel share the same persistence path.
    """

    def __init__(self, db: Database) -> None:
        self._store = SessionStore(db)

    def list_messages(self, session_id: str, workspace_id: str) -> list[dict[str, object]]:
        return self._store.get_history(session_id, workspace_id)

    def get_latest_summary(self, workspace_id: str, session_id: str) -> dict[str, object] | None:
        return self._store.get_latest_summary(workspace_id, session_id)

    def update_summary(self, workspace_id: str, session_id: str) -> dict[str, object] | None:
        return self._store.update_summary(workspace_id, session_id)

    def trim_messages(self, session_id: str, workspace_id: str, keep_count: int) -> int:
        return self._store.trim_messages(session_id, workspace_id, keep_count)

    def message_count(self, session_id: str, workspace_id: str) -> int:
        return self._store.message_count(session_id, workspace_id)

    def persist_interrupted_turn(
        self,
        *,
        event_json: str,
        turn_state: str,
        model_call_count: int,
        tool_call_count: int,
    ) -> None:
        self._store.persist_interrupted_turn(
            event_json=event_json,
            turn_state=turn_state,
            model_call_count=model_call_count,
            tool_call_count=tool_call_count,
        )

    def latest_assistant_message_id(self, workspace_id: str, session_id: str) -> str | None:
        return self._store.latest_assistant_message_id(workspace_id, session_id)

    def persist_user_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        content: str,
        title_if_empty: str,
    ) -> None:
        self._store.append_user_message(
            session_id, workspace_id, content,
            message_id=message_id,
            title_if_empty=title_if_empty,
        )

    def persist_assistant_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        content: str,
        trace_id: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self._store.append_assistant_message(
            session_id, workspace_id, content,
            message_id=message_id,
            trace_id=trace_id,
            metadata=metadata,
        )
