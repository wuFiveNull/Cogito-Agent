from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.queue.message import InboundMessage
from cogito_agent.storage.database import Database


class InputQueueRepository:
    """SQLite CRUD for the ``input_queue`` table.

    Stores inbound messages before AgentLoop consumes them, enabling
    crash recovery via the ``status`` state machine::

        pending → processing → done
                           ↘  failed
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── write ──────────────────────────────────────────────────────────

    def insert(self, msg: InboundMessage, task_type: str = "user_message") -> str:
        """Persist an inbound message and return its queue id.

        ``task_type`` distinguishes user messages from drift tasks, etc.
        """
        mid = str(uuid.uuid4())
        payload = {
            "channel": msg.channel,
            "session_id": msg.session_id,
            "workspace_id": msg.workspace_id,
            "content": msg.content,
            "media": msg.media,
            "metadata": msg.metadata,
        }
        self._db.connection.execute(
            "INSERT INTO input_queue (id, channel, workspace_id, session_id,"
            " payload_json, status, task_type)"
            " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (mid, msg.channel, msg.workspace_id, msg.session_id,
             json.dumps(payload, ensure_ascii=False), task_type),
        )
        self._db.connection.commit()
        return mid

    def update_status(self, msg_id: str, status: str, error: str = "") -> None:
        """Transition a queue item to a new status."""
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        if status == "processing":
            self._db.connection.execute(
                "UPDATE input_queue SET status=?, started_at=?, retry_count=retry_count+1"
                " WHERE id=?",
                (status, now, msg_id),
            )
        elif status == "done":
            self._db.connection.execute(
                "UPDATE input_queue SET status=?, done_at=? WHERE id=?",
                (status, now, msg_id),
            )
        elif status == "failed":
            self._db.connection.execute(
                "UPDATE input_queue SET status=?, done_at=?, error=? WHERE id=?",
                (status, now, error, msg_id),
            )
        else:
            self._db.connection.execute(
                "UPDATE input_queue SET status=? WHERE id=?", (status, msg_id)
            )
        self._db.connection.commit()

    # ── read ───────────────────────────────────────────────────────────

    def list_by_status(
        self, *statuses: str, task_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        if task_type:
            cur = self._db.connection.execute(
                f"SELECT * FROM input_queue WHERE status IN ({placeholders})"
                " AND task_type=? ORDER BY created_at ASC LIMIT ?",
                (*statuses, task_type, limit),
            )
        else:
            cur = self._db.connection.execute(
                f"SELECT * FROM input_queue WHERE status IN ({placeholders})"
                " ORDER BY created_at ASC LIMIT ?",
                (*statuses, limit),
            )
        return [dict(row) for row in cur.fetchall()]

    def list_by_task_type(
        self, task_type: str, *statuses: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List queue items by task type and optional statuses."""
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            cur = self._db.connection.execute(
                f"SELECT * FROM input_queue WHERE task_type=?"
                f" AND status IN ({placeholders}) ORDER BY created_at ASC LIMIT ?",
                (task_type, *statuses, limit),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM input_queue WHERE task_type=?"
                " ORDER BY created_at ASC LIMIT ?",
                (task_type, limit),
            )
        return [dict(row) for row in cur.fetchall()]

    def get_by_id(self, msg_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM input_queue WHERE id=?", (msg_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def count_by_status(self) -> dict[str, int]:
        cur = self._db.connection.execute(
            "SELECT status, COUNT(*) AS cnt FROM input_queue GROUP BY status"
        )
        result: dict[str, int] = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
        for row in cur.fetchall():
            result[str(row["status"])] = row["cnt"]
        return result

    # ── recovery ───────────────────────────────────────────────────────

    def recover_pending(
        self, processing_timeout_secs: int = 300, task_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Return messages to retry after crash recovery.

        Includes:
        - status='pending' (never processed)
        - status='processing' and started_at exceeds timeout (crashed)

        If ``task_type`` is provided, only recover messages of that type.
        """
        from datetime import timedelta

        timeout = datetime.now(UTC) - timedelta(seconds=processing_timeout_secs)
        timeout_str = timeout.strftime("%Y-%m-%d %H:%M:%S")
        task_filter = " AND task_type=?" if task_type else ""
        params: list[Any] = [timeout_str]
        if task_type:
            params.append(task_type)
        cur = self._db.connection.execute(
            f"SELECT * FROM input_queue WHERE"
            f" ((status='pending')"
            f" OR (status='processing' AND started_at < ?))"
            f"{task_filter}"
            f" ORDER BY created_at ASC",
            tuple(params),
        )
        rows = [dict(row) for row in cur.fetchall()]
        # Reset expired processing rows back to pending
        for row in rows:
            if row["status"] == "processing":
                self._db.connection.execute(
                    "UPDATE input_queue SET status='pending', started_at=NULL"
                    " WHERE id=?",
                    (str(row["id"]),),
                )
                self._db.connection.commit()
        return rows

    @staticmethod
    def row_to_inbound(row: dict[str, Any]) -> InboundMessage:
        """Convert a DB row back to an InboundMessage for reprocessing."""
        payload = json.loads(str(row.get("payload_json", "{}")))
        return InboundMessage(
            channel=str(payload.get("channel", "")),
            session_id=str(payload.get("session_id", "")),
            workspace_id=str(payload.get("workspace_id", "")),
            content=str(payload.get("content", "")),
            media=payload.get("media"),
            metadata={
                **(payload.get("metadata") or {}),
                "queue_id": str(row["id"]),
            },
        )

    def delete_old_done(self, before_days: int = 7) -> int:
        """Clean up successfully processed messages older than ``before_days``."""
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=before_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        cur = self._db.connection.execute(
            "DELETE FROM input_queue WHERE status IN ('done','failed') AND done_at < ?",
            (cutoff,),
        )
        self._db.connection.commit()
        return cur.rowcount
