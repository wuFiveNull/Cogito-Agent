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
        commit: bool = True,
    ) -> str:
        mid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT INTO outbox_messages"
            " (id, event_id, decision_id, workspace_id, user_id, title, body,"
            " status, priority, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                mid,
                event_id,
                decision_id,
                workspace_id,
                user_id,
                title,
                body,
                "pending",
                priority,
                source,
                trace_id or None,
                now,
            ),
        )
        if commit:
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

    def mark_read(self, message_id: str) -> bool:
        cursor = self._db.connection.execute(
            "UPDATE outbox_messages SET read_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), message_id),
        )
        self._db.connection.commit()
        return cursor.rowcount == 1

    def dismiss(self, message_id: str) -> bool:
        cursor = self._db.connection.execute(
            "UPDATE outbox_messages SET dismissed_at=?, status='skipped' WHERE id=?",
            (datetime.now(UTC).isoformat(), message_id),
        )
        self._db.connection.commit()
        return cursor.rowcount == 1

    def retry(self, message_id: str) -> bool:
        cursor = self._db.connection.execute(
            "UPDATE outbox_messages SET status='pending', last_error=NULL,"
            " next_retry_at=NULL, delivery_attempts=0 WHERE id=?",
            (message_id,),
        )
        self._db.connection.commit()
        return cursor.rowcount == 1

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

    def list_all(self, workspace_id: str = "*", limit: int = 50) -> list[dict[str, Any]]:
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

    def list_messages_filtered(
        self,
        workspace_id: str = "*",
        status: str = "",
        time_range: str = "all",
        q: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clauses: list[str] = []

        if workspace_id != "*":
            where_clauses.append("workspace_id=?")
            params.append(workspace_id)

        if status and status != "all":
            where_clauses.append("status=?")
            params.append(status)

        if q:
            where_clauses.append("(title LIKE ? OR body LIKE ? OR id LIKE ? OR decision_id LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like, like])

        if time_range and time_range != "all":
            from datetime import timedelta

            days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
            days = days_map.get(time_range, 0)
            if days:
                cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                where_clauses.append("created_at >= ?")
                params.append(cutoff)

        where = ""
        if where_clauses:
            where = "WHERE " + " AND ".join(where_clauses)

        cur = self._db.connection.execute(
            f"SELECT * FROM outbox_messages {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_by_status(self, workspace_id: str = "*") -> dict[str, int]:
        where = "WHERE workspace_id=?" if workspace_id != "*" else ""
        params = (workspace_id,) if workspace_id != "*" else ()
        cur = self._db.connection.execute(
            f"SELECT status, COUNT(*) AS cnt FROM outbox_messages {where} GROUP BY status",
            params,
        )
        result: dict[str, int] = {"pending": 0, "sent": 0, "failed": 0, "skipped": 0}
        for r in cur.fetchall():
            result[str(r["status"])] = r["cnt"]
        return result
