"""ApprovalReader — approval_records / outbox_messages 只读查询。"""

from __future__ import annotations

from typing import Any

from cogito_agent.storage import Database


class ApprovalReader:
    """审批记录和出站消息的只读查询。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Approval Records ───────────────────────────────────────────────────

    def list_pending_approvals(
        self, workspace_id: str = "default"
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, actor_id, capability_name,"
            " operation, resource, reason, tool_call_json, status,"
            " created_at, updated_at"
            " FROM approval_records"
            " WHERE workspace_id = ? AND status = 'pending'"
            " ORDER BY created_at DESC",
            (workspace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def list_approvals_by_filters(
        self,
        workspace_id: str = "",
        *,
        status: str = "",
        risk: str = "",
        q: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """兼容现有 ApprovalRepository.list_by_filters。"""
        where: list[str] = []
        params: list[object] = []
        if workspace_id:
            where.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            where.append("status = ?")
            params.append(status)
        if risk:
            # risk 不是表字段，但当前代码传了；忽略它不报错
            pass
        if q:
            where.append("(id LIKE ? OR capability_name LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cur = self._db.connection.execute(
            f"SELECT id, workspace_id, actor_id, capability_name,"
            f" operation, resource, reason, status, created_at, updated_at"
            f" FROM approval_records {where_sql}"
            f" ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_pending_approvals(self, workspace_id: str = "default") -> int:
        row = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM approval_records"
            " WHERE workspace_id = ? AND status = 'pending'",
            (workspace_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    def get_approval(self, approval_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records WHERE id = ?", (approval_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    # ── Outbox (delivery queue) ────────────────────────────────────────────

    def list_outbox_by_filters(
        self,
        workspace_id: str = "default",
        *,
        status: str = "",
        q: str = "",
        time_range: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """兼容现有 OutboxRepository.list_by_filters。"""
        where: list[str] = []
        params: list[object] = []
        if workspace_id:
            where.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            where.append("status = ?")
            params.append(status)
        if time_range:
            where.append("created_at >= ?")
            params.append(time_range)
        if q:
            where.append("(id LIKE ? OR source_key LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        cur = self._db.connection.execute(
            f"SELECT id, workspace_id, source_key, delivery_key,"
            f" status, error_message, created_at, sent_at"
            f" FROM outbox_messages {where_sql}"
            f" ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_outbox_by_status(
        self, statuses: tuple[str, ...], workspace_id: str = ""
    ) -> int:
        placeholders = ", ".join("?" for _ in statuses)
        params: list[object] = list(statuses)
        if workspace_id:
            params.append(workspace_id)
            row = self._db.connection.execute(
                f"SELECT COUNT(*) AS cnt FROM outbox_messages"
                f" WHERE status IN ({placeholders}) AND workspace_id = ?",
                params,
            ).fetchone()
        else:
            row = self._db.connection.execute(
                f"SELECT COUNT(*) AS cnt FROM outbox_messages"
                f" WHERE status IN ({placeholders})",
                params,
            ).fetchone()
        return row["cnt"] if row else 0

    def list_failed_outbox(
        self, workspace_id: str = "", limit: int = 5
    ) -> list[dict[str, object]]:
        where_clause = ""
        params: list[object] = ["failed", "dead_letter"]
        if workspace_id:
            where_clause = " AND workspace_id = ?"
            params.append(workspace_id)
        cur = self._db.connection.execute(
            f"SELECT id, workspace_id, source_key, delivery_key,"
            f" status, error_message, created_at"
            f" FROM outbox_messages"
            f" WHERE status IN (?, ?){where_clause}"
            f" ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Drift runs ─────────────────────────────────────────────────────────

    def list_failed_drift_runs(
        self, since: str, workspace_id: str = "", limit: int = 5
    ) -> list[dict[str, object]]:
        params: list[object] = [since]
        ws_clause = ""
        if workspace_id:
            ws_clause = " AND workspace_id = ?"
            params.append(workspace_id)
        cur = self._db.connection.execute(
            f"SELECT id, skill_name, error_message"
            f" FROM drift_runs"
            f" WHERE status='failed' AND created_at >= ?{ws_clause}"
            f" ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def count_failed_drift_runs(
        self, since: str, workspace_id: str = ""
    ) -> int:
        params: list[object] = [since]
        ws_clause = ""
        if workspace_id:
            ws_clause = " AND workspace_id = ?"
            params.append(workspace_id)
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM drift_runs"
            f" WHERE status='failed' AND created_at >= ?{ws_clause}",
            params,
        ).fetchone()
        return row["cnt"] if row else 0
