"""AuditReader — audit_logs 只读查询。"""

from __future__ import annotations

from typing import Any

from cogito_agent.storage import Database


class AuditReader:
    """审计日志的只读查询。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_audit_logs(
        self,
        workspace_id: str = "default",
        *,
        action: str = "",
        actor: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        where: list[str] = []
        params: list[object] = []
        if workspace_id and workspace_id != "*":
            where.append("al.workspace_id = ?")
            params.append(workspace_id)
        if action:
            where.append("al.action = ?")
            params.append(action)
        if actor:
            where.append("al.actor_id = ?")
            params.append(actor)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cur = self._db.connection.execute(
            f"SELECT al.id, al.actor_id, al.action, al.resource,"
            f" al.workspace_id, al.session_id, al.trace_id,"
            f" al.decision, al.reason, al.created_at"
            f" FROM audit_logs al {where_sql}"
            f" ORDER BY al.created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def list_audit_by_filters(
        self,
        workspace_id: str = "default",
        *,
        action: str = "",
        actor: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """兼容现有 AuditRepository.list_by_filters。"""
        return self.list_audit_logs(
            workspace_id, action=action, actor=actor, limit=limit
        )

    def count_audit_logs(
        self, since: str = "", workspace_id: str = ""
    ) -> int:
        where: list[str] = []
        params: list[object] = []
        if workspace_id and workspace_id != "*":
            where.append("workspace_id = ?")
            params.append(workspace_id)
        if since:
            where.append("created_at >= ?")
            params.append(since)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM audit_logs {where_sql}", params
        ).fetchone()
        return row["cnt"] if row else 0

    def get_audit_detail(self, audit_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM audit_logs WHERE id = ?", (audit_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
