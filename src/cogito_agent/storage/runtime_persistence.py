from __future__ import annotations

import json

from cogito_agent.context import SessionCompressionService

from .database import Database
from .repositories import MessageRepository


class SqliteRuntimePersistence:
    """SQLite adapter for RuntimeKernel's persistence port."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._messages = MessageRepository(db)
        self._compression = SessionCompressionService(db)

    def list_messages(self, session_id: str, workspace_id: str) -> list[dict[str, object]]:
        return [dict(row) for row in self._messages.list_by_session(session_id, workspace_id)]

    def get_latest_summary(self, workspace_id: str, session_id: str) -> dict[str, object] | None:
        return self._compression.get_latest(workspace_id, session_id)

    def update_summary(self, workspace_id: str, session_id: str) -> dict[str, object] | None:
        return self._compression.update_summary(workspace_id, session_id)

    def persist_interrupted_turn(
        self,
        *,
        event_json: str,
        turn_state: str,
        model_call_count: int,
        tool_call_count: int,
    ) -> None:
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO interrupted_turns"
                " (event_json, turn_state, model_call_count, tool_call_count)"
                " VALUES (?, ?, ?, ?)",
                (event_json, turn_state, model_call_count, tool_call_count),
            )

    def latest_assistant_message_id(self, workspace_id: str, session_id: str) -> str | None:
        row = self._db.connection.execute(
            "SELECT id FROM messages WHERE workspace_id=? AND session_id=?"
            " AND role='assistant' ORDER BY rowid DESC LIMIT 1",
            (workspace_id, session_id),
        ).fetchone()
        return str(row["id"]) if row else None

    def persist_user_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        content: str,
        title_if_empty: str,
    ) -> None:
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO messages"
                " (id, workspace_id, session_id, role, content, metadata_json)"
                " VALUES (?, ?, ?, 'user', ?, '{}')",
                (message_id, workspace_id, session_id, content),
            )
            self._db.connection.execute(
                "UPDATE sessions SET title=CASE WHEN title IS NULL OR title=''"
                " THEN ? ELSE title END, updated_at=datetime('now')"
                " WHERE id=? AND workspace_id=?",
                (title_if_empty, session_id, workspace_id),
            )

    def trim_messages(
        self, session_id: str, workspace_id: str, keep_count: int
    ) -> int:
        """Delete old messages, keeping only the most recent *keep_count*.

        Returns the number of deleted rows.
        """
        row = self._db.connection.execute(
            "SELECT rowid FROM messages"
            " WHERE workspace_id=? AND session_id=?"
            " ORDER BY rowid DESC LIMIT 1 OFFSET ?",
            (workspace_id, session_id, keep_count - 1),
        ).fetchone()
        if row is None:
            return 0
        cutoff = int(row["rowid"])
        deleted = self._db.connection.execute(
            "DELETE FROM messages"
            " WHERE workspace_id=? AND session_id=? AND rowid <= ?",
            (workspace_id, session_id, cutoff),
        ).rowcount
        self._db.connection.commit()
        return deleted

    def message_count(self, session_id: str, workspace_id: str) -> int:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM messages"
            " WHERE workspace_id=? AND session_id=?",
            (workspace_id, session_id),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def persist_assistant_message(
        self,
        *,
        message_id: str,
        workspace_id: str,
        session_id: str,
        content: str,
        trace_id: str,
    ) -> None:
        metadata = json.dumps({"trace_id": trace_id}) if trace_id else "{}"
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO messages"
                " (id, workspace_id, session_id, role, content, metadata_json)"
                " VALUES (?, ?, ?, 'assistant', ?, ?)",
                (message_id, workspace_id, session_id, content, metadata),
            )
            self._db.connection.execute(
                "UPDATE sessions SET updated_at=datetime('now') WHERE id=? AND workspace_id=?",
                (session_id, workspace_id),
            )
