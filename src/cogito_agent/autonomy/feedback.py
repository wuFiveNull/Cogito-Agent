from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database


class FeedbackValue(StrEnum):
    useful = "useful"
    not_useful = "not_useful"
    too_many = "too_many"
    wrong_time = "wrong_time"
    irrelevant = "irrelevant"


class FeedbackStore:
    def __init__(self, db: Database, audit_logger: AuditLogger | None = None) -> None:
        self._db = db
        self._audit = audit_logger or AuditLogger(db)

    def record_feedback(
        self,
        decision_id: str,
        event_id: str,
        value: str,
        comment: str = "",
        workspace_id: str = "*",
        user_id: str = "",
        trace_id: str = "",
    ) -> str:
        fid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT INTO feedback_entries"
            " (id, decision_id, event_id, workspace_id, user_id, value, comment,"
            " trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fid,
                decision_id,
                event_id,
                workspace_id,
                user_id,
                value,
                comment,
                trace_id or None,
                now,
            ),
        )
        self._db.connection.commit()

        self._audit.log(
            actor_id="user",
            action="autonomy.feedback",
            resource=f"decision:{decision_id}",
            workspace_id=workspace_id,
            decision="allow",
            reason=f"feedback:{value}",
            details=f'{{"feedback_id":"{fid}","value":"{value}"}}',
        )
        return fid

    def get_feedback_for_decision(self, decision_id: str) -> list[dict[str, Any]]:
        cur = self._db.connection.execute(
            "SELECT * FROM feedback_entries WHERE decision_id = ? ORDER BY created_at DESC",
            (decision_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_recent_feedback(self, workspace_id: str, limit: int = 10) -> list[str]:
        cur = self._db.connection.execute(
            "SELECT value FROM feedback_entries"
            " WHERE workspace_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [r["value"] for r in cur.fetchall() if r["value"]]

    def list_feedback(
        self,
        workspace_id: str = "*",
        value: str = "",
        time_range: str = "all",
        decision_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clauses: list[str] = []

        if workspace_id != "*":
            where_clauses.append("workspace_id=?")
            params.append(workspace_id)

        if value and value != "all":
            where_clauses.append("value=?")
            params.append(value)

        if decision_id:
            where_clauses.append("decision_id=?")
            params.append(decision_id)

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
            f"SELECT * FROM feedback_entries {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_by_value(self, workspace_id: str = "*") -> dict[str, int]:
        where = "WHERE workspace_id=?" if workspace_id != "*" else ""
        params = (workspace_id,) if workspace_id != "*" else ()
        cur = self._db.connection.execute(
            f"SELECT value, COUNT(*) AS cnt FROM feedback_entries {where} GROUP BY value",
            params,
        )
        result: dict[str, int] = {
            "useful": 0,
            "not_useful": 0,
            "too_many": 0,
            "wrong_time": 0,
            "irrelevant": 0,
        }
        for r in cur.fetchall():
            result[str(r["value"])] = r["cnt"]
        return result
