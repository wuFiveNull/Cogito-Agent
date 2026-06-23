"""SessionReader — 会话/消息只读查询，不依赖 RuntimeKernel。"""

from __future__ import annotations

from typing import Any

from cogito_agent.storage import Database


class SessionReader:
    """会话和消息的只读查询。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Session ─────────────────────────────────────────────────────────────

    def list_sessions(
        self, workspace_id: str = "default", limit: int = 50, offset: int = 0
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, title, summary, created_at, updated_at"
            " FROM sessions"
            " WHERE workspace_id = ? AND deleted_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_session(
        self, session_id: str, workspace_id: str = "default"
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, title, summary, created_at, updated_at"
            " FROM sessions"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (session_id, workspace_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def count_sessions(self, workspace_id: str = "default") -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM sessions"
            " WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    # ── Messages ────────────────────────────────────────────────────────────

    def list_messages(
        self,
        session_id: str,
        workspace_id: str = "default",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT id, session_id, workspace_id, role, content,"
            " metadata_json, created_at"
            " FROM messages"
            " WHERE session_id = ? AND workspace_id = ?"
            " ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (session_id, workspace_id, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_messages(
        self, session_id: str, workspace_id: str = "default"
    ) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM messages"
            " WHERE session_id = ? AND workspace_id = ?",
            (session_id, workspace_id),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    # ── Session stats ───────────────────────────────────────────────────────

    def session_stats(self, workspace_id: str = "default") -> dict[str, int]:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM sessions"
            " WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,),
        ).fetchone()
        total_sessions = row["cnt"] if row else 0

        row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM messages m"
            " JOIN sessions s ON m.session_id = s.id"
            " WHERE m.workspace_id = ? AND s.deleted_at IS NULL",
            (workspace_id,),
        ).fetchone()
        total_messages = row["cnt"] if row else 0

        row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM messages m"
            " JOIN sessions s ON m.session_id = s.id"
            " WHERE m.workspace_id = ? AND m.role = 'user' AND s.deleted_at IS NULL",
            (workspace_id,),
        ).fetchone()
        user_msgs = row["cnt"] if row else 0

        return {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "user_messages": user_msgs,
        }

    # ── Session summary ─────────────────────────────────────────────────────

    def get_latest_summary(
        self, workspace_id: str, session_id: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT id, summary, through_message_id, parent_summary_id"
            " FROM session_summaries"
            " WHERE workspace_id = ? AND session_id = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (workspace_id, session_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None
