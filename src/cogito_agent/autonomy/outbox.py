from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database


class Outbox:
    def __init__(self, db: Database) -> None:
        self._db = db

    def enqueue(
        self,
        event_id: str,
        decision_id: str,
        title: str,
        body: str = "",
        workspace_id: str = "*",
        user_id: str = "",
        priority: str = "normal",
        source: str = "system",
        trace_id: str = "",
    ) -> str:
        mid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT INTO outbox_messages"
            " (id, event_id, decision_id, workspace_id, user_id, title, body,"
            " status, priority, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, event_id, decision_id, workspace_id, user_id, title, body,
             "pending", priority, source, trace_id or None, now),
        )
        self._db.connection.commit()
        return mid

    def mark_sent(self, message_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE outbox_messages SET status = 'sent', sent_at = ? WHERE id = ?",
            (now, message_id),
        )
        self._db.connection.commit()

    def mark_failed(self, message_id: str, error: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE outbox_messages SET status = 'failed', sent_at = ? WHERE id = ?",
            (now, message_id),
        )
        self._db.connection.commit()

    def list_pending(self, workspace_id: str = "*", limit: int = 50) -> list[dict[str, Any]]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM outbox_messages WHERE status = 'pending'"
                " ORDER BY created_at ASC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM outbox_messages"
                " WHERE status = 'pending' AND workspace_id = ?"
                " ORDER BY created_at ASC LIMIT ?",
                (workspace_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def list_all(
        self, workspace_id: str = "*", limit: int = 50
    ) -> list[dict[str, Any]]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM outbox_messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM outbox_messages WHERE workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM outbox_messages WHERE id = ?", (message_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
