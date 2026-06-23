from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import DecisionRepository as _DecisionRepository


class DecisionStore:
    """Wraps ``notification_decisions`` table via DecisionRepository."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._repo = _DecisionRepository(db)

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
        commit: bool = True,
    ) -> None:
        decision: dict[str, object] = {
            "id": decision_id,
            "event_id": event_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "action": action,
            "reason_code": reason_code,
            "reason": reason,
            "cost_score": cost_score,
            "priority_score": priority_score,
            "dedup_hit": dedup_hit,
            "quiet_hours_hit": quiet_hours_hit,
            "quota_hit": quota_hit,
            "requires_approval": requires_approval,
            "trace_id": trace_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._repo.save(decision)
        if commit:
            self._db.connection.commit()

    def list_decisions(self, workspace_id: str = "*", limit: int = 50) -> list[dict[str, Any]]:
        return self._repo.list_by_workspace(workspace_id, limit=limit)

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM notification_decisions WHERE id = ?",
            (decision_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def count_push_recent(self, workspace_id: str, minutes: int = 60) -> int:
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
            f"SELECT action, COUNT(*) AS cnt FROM notification_decisions {where} GROUP BY action",
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
            f"SELECT * FROM notification_decisions {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]
