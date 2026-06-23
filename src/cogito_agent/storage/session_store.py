from __future__ import annotations

import json
import uuid
from typing import Any

from cogito_agent.storage.database import Database
from cogito_agent.storage.repositories import MessageRepository, SessionRepository


class SessionStore:
    """Unified session and message persistence interface.

    Provides a higher-level API over the ``messages`` and ``sessions``
    tables, used by both ``SqliteRuntimePersistence`` (kernel-side) and
    eventually by console management views.  This decouples message
    storage logic from the kernel's processing pipeline.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._messages = MessageRepository(db)
        self._sessions = SessionRepository(db)

    # ── message persistence ────────────────────────────────────────────

    def append_user_message(
        self,
        session_id: str,
        workspace_id: str,
        content: str,
        *,
        message_id: str | None = None,
        title_if_empty: str = "",
    ) -> str:
        """Persist a user message and return its id.

        If ``message_id`` is provided it is used as the primary key;
        otherwise one is auto-generated.
        Auto-updates the session title if it's currently empty.
        """
        mid = message_id or str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO messages (id, workspace_id, session_id, role, content, metadata_json)"
            " VALUES (?, ?, ?, 'user', ?, '{}')",
            (mid, workspace_id, session_id, content),
        )
        if title_if_empty:
            self._db.connection.execute(
                "UPDATE sessions SET title=CASE WHEN title IS NULL OR title=''"
                " THEN ? ELSE title END, updated_at=datetime('now')"
                " WHERE id=? AND workspace_id=?",
                (title_if_empty, session_id, workspace_id),
            )
        else:
            self._db.connection.execute(
                "UPDATE sessions SET updated_at=datetime('now')"
                " WHERE id=? AND workspace_id=?",
                (session_id, workspace_id),
            )
        self._db.connection.commit()
        return mid

    def append_assistant_message(
        self,
        session_id: str,
        workspace_id: str,
        content: str,
        *,
        message_id: str | None = None,
        trace_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> str:
        """Persist an assistant message and return its id.

        If ``message_id`` is provided it is used as the primary key;
        otherwise one is auto-generated.
        ``metadata`` is serialized to the ``metadata_json`` column and
        typically includes token counts, model name, provider, etc.
        """
        mid = message_id or str(uuid.uuid4())
        meta = dict(metadata or {})
        if trace_id:
            meta.setdefault("trace_id", trace_id)
        metadata_json = json.dumps(meta, ensure_ascii=False)
        self._db.connection.execute(
            "INSERT INTO messages (id, workspace_id, session_id, role, content, metadata_json)"
            " VALUES (?, ?, ?, 'assistant', ?, ?)",
            (mid, workspace_id, session_id, content, metadata_json),
        )
        self._db.connection.execute(
            "UPDATE sessions SET updated_at=datetime('now')"
            " WHERE id=? AND workspace_id=?",
            (session_id, workspace_id),
        )
        self._db.connection.commit()
        return mid

    # ── history reading ────────────────────────────────────────────────

    def get_history(
        self, session_id: str, workspace_id: str
    ) -> list[dict[str, Any]]:
        """Return all messages for a session, ordered by creation time."""
        return [dict(row) for row in self._messages.list_by_session(session_id, workspace_id)]

    def message_count(self, session_id: str, workspace_id: str) -> int:
        """Count messages in a session."""
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM messages"
            " WHERE workspace_id=? AND session_id=?",
            (workspace_id, session_id),
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def latest_assistant_message_id(self, workspace_id: str, session_id: str) -> str | None:
        """Return the id of the most recent assistant message, if any."""
        row = self._db.connection.execute(
            "SELECT id FROM messages WHERE workspace_id=? AND session_id=?"
            " AND role='assistant' ORDER BY rowid DESC LIMIT 1",
            (workspace_id, session_id),
        ).fetchone()
        return str(row["id"]) if row else None

    def get_latest_summary(self, workspace_id: str, session_id: str) -> dict[str, Any] | None:
        """Return the latest session summary (used for context compression)."""
        from cogito_agent.context import SessionCompressionService

        return SessionCompressionService(self._db).get_latest(workspace_id, session_id)

    def update_summary(self, workspace_id: str, session_id: str) -> dict[str, Any] | None:
        """Trigger summary update for context compression."""
        from cogito_agent.context import SessionCompressionService

        return SessionCompressionService(self._db).update_summary(workspace_id, session_id)

    # ── maintenance ────────────────────────────────────────────────────

    def trim_messages(self, session_id: str, workspace_id: str, keep_count: int) -> int:
        """Delete old messages, keeping only the most recent ``keep_count``.

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

    def persist_interrupted_turn(
        self,
        *,
        event_json: str,
        turn_state: str,
        model_call_count: int,
        tool_call_count: int,
    ) -> None:
        """Save an interrupted turn record for recovery."""
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO interrupted_turns"
                " (event_json, turn_state, model_call_count, tool_call_count)"
                " VALUES (?, ?, ?, ?)",
                (event_json, turn_state, model_call_count, tool_call_count),
            )
