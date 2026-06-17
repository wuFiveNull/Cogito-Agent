from __future__ import annotations

from datetime import UTC, datetime, timedelta
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

    def count_by_action(self, workspace_id: str = "*") -> dict[str, int]:
        where = "WHERE workspace_id=?" if workspace_id != "*" else ""
        params = (workspace_id,) if workspace_id != "*" else ()
        cur = self._db.connection.execute(
            "SELECT action, COUNT(*) AS cnt FROM notification_decisions"
            f" {where} GROUP BY action",
            params,
        )
        result: dict[str, int] = {"push": 0, "skip": 0, "defer": 0, "require_approval": 0}
        for r in cur.fetchall():
            result[str(r["action"])] = r["cnt"]
        return result

    def list_decisions_filtered(
        self,
        workspace_id: str = "*",
        action: str = "",
        reason_code: str = "",
        time_range: str = "all",
        q: str = "",
        trace_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clauses: list[str] = []

        if workspace_id != "*":
            where_clauses.append("workspace_id=?")
            params.append(workspace_id)

        if action and action != "all":
            where_clauses.append("action=?")
            params.append(action)

        if reason_code:
            where_clauses.append("reason_code LIKE ?")
            params.append(f"%{reason_code}%")

        if q:
            where_clauses.append(
                "(id LIKE ? OR event_id LIKE ? OR reason LIKE ? OR trace_id LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like])

        if trace_id:
            where_clauses.append("trace_id=?")
            params.append(trace_id)

        if time_range and time_range != "all":
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
            "SELECT * FROM notification_decisions"
            f" {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]
