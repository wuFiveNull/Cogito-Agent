from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database


class DecisionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save_decision(
        self,
        decision_id: str,
        event_id: str,
        workspace_id: str,
        user_id: str,
        action: str,
        reason_code: str,
        reason: str,
        cost_score: float,
        priority_score: float,
        dedup_hit: bool,
        quiet_hours_hit: bool,
        quota_hit: bool,
        requires_approval: bool,
        trace_id: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT INTO notification_decisions"
            " (id, event_id, workspace_id, user_id, action, reason_code, reason,"
            " cost_score, priority_score, dedup_hit, quiet_hours_hit, quota_hit,"
            " requires_approval, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id, event_id, workspace_id, user_id,
                action, reason_code, reason,
                cost_score, priority_score,
                1 if dedup_hit else 0, 1 if quiet_hours_hit else 0,
                1 if quota_hit else 0,
                1 if requires_approval else 0,
                trace_id, now,
            ),
        )
        self._db.connection.commit()

    def list_decisions(
        self, workspace_id: str = "*", limit: int = 50
    ) -> list[dict[str, Any]]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM notification_decisions"
                " ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM notification_decisions"
                " WHERE workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [dict(r) for r in cur.fetchall()]

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM notification_decisions WHERE id = ?",
            (decision_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def count_push_recent(self, workspace_id: str, minutes: int = 60) -> int:
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notification_decisions"
            " WHERE workspace_id = ? AND action = 'push' AND created_at >= ?",
            (workspace_id, cutoff),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0
