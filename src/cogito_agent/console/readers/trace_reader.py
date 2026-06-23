"""TraceReader — traces / spans / model_calls / tool_calls 只读查询。"""

from __future__ import annotations

from typing import Any

from cogito_agent.storage import Database


class TraceReader:
    """追踪数据的只读查询。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Traces ─────────────────────────────────────────────────────────────

    def list_traces(
        self,
        workspace_id: str = "default",
        *,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        params: list[object] = []
        where_clauses: list[str] = []
        if workspace_id and workspace_id != "*":
            where_clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status:
            where_clauses.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cur = self._db.connection.execute(
            f"SELECT id, workspace_id, session_id, root_event_id,"
            f" status, started_at, ended_at"
            f" FROM traces {where}"
            f" ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_trace(self, trace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, session_id, root_event_id,"
            " status, started_at, ended_at"
            " FROM traces WHERE id = ?",
            (trace_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_trace_with_children(self, trace_id: str) -> dict[str, object] | None:
        """返回 trace + spans + model_calls + tool_calls + audits。"""
        trace = self.get_trace(trace_id)
        if trace is None:
            return None

        spans = self._db.connection.execute(
            "SELECT id, name, kind, parent_span_id, status,"
            " input_summary, output_summary, started_at, ended_at"
            " FROM spans WHERE trace_id = ? ORDER BY started_at",
            (trace_id,),
        ).fetchall()
        trace["spans"] = [dict(r) for r in spans]

        mc = self._db.connection.execute(
            "SELECT provider, model, input_token_count, output_token_count,"
            " latency_ms, stop_reason, error"
            " FROM model_calls WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        ).fetchall()
        trace["model_calls"] = [dict(r) for r in mc]

        tc = self._db.connection.execute(
            "SELECT capability_name, decision, status, latency_ms, error"
            " FROM tool_calls WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        ).fetchall()
        trace["tool_calls"] = [dict(r) for r in tc]

        audit = self._db.connection.execute(
            "SELECT action, decision, reason, created_at FROM audit_logs"
            " WHERE trace_id = ? ORDER BY created_at",
            (trace_id,),
        ).fetchall()
        trace["audits"] = [dict(r) for r in audit]

        return trace

    def list_traces_by_filters(
        self,
        workspace_id: str = "default",
        *,
        status: str = "",
        q: str = "",
        time_range: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        """带过滤条件的 trace 列表，兼容现有 TraceRepository.list_by_filters。"""
        where_clauses: list[str] = []
        params: list[object] = []
        if workspace_id and workspace_id != "*":
            where_clauses.append("t.workspace_id = ?")
            params.append(workspace_id)
        if status:
            where_clauses.append("t.status = ?")
            params.append(status)
        if time_range:
            where_clauses.append("t.started_at >= ?")
            params.append(time_range)
        if q:
            where_clauses.append(
                "(t.id LIKE ? OR t.session_id LIKE ? OR s.title LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like])

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cur = self._db.connection.execute(
            f"SELECT t.id, t.workspace_id, t.session_id, t.root_event_id,"
            f" t.status, t.started_at, t.ended_at, s.title as session_title"
            f" FROM traces t"
            f" LEFT JOIN sessions s ON t.session_id = s.id AND t.workspace_id = s.workspace_id"
            f" {where}"
            f" ORDER BY t.started_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Counts ─────────────────────────────────────────────────────────────

    def count_traces(
        self,
        since: str = "",
        workspace_id: str = "default",
        *,
        failed_only: bool = False,
    ) -> int:
        where: list[str] = []
        params: list[object] = []
        if workspace_id and workspace_id != "*":
            where.append("workspace_id = ?")
            params.append(workspace_id)
        if since:
            where.append("started_at >= ?")
            params.append(since)
        if failed_only:
            where.append("status = 'error'")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM traces {where_sql}", params
        ).fetchone()
        return row["cnt"] if row else 0

    def count_model_calls(
        self, since: str = "", workspace_id: str = "default"
    ) -> int:
        params: list[object] = []
        where: list[str] = []
        if workspace_id and workspace_id != "*":
            where.append("t.workspace_id = ?")
            params.append(workspace_id)
        if since:
            where.append("m.started_at >= ?")
            params.append(since)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM model_calls m"
            f" JOIN traces t ON m.trace_id = t.id"
            f" {where_sql}",
            params,
        ).fetchone()
        return row["cnt"] if row else 0

    def avg_model_latency(
        self, since: str = "", workspace_id: str = "default"
    ) -> float:
        params: list[object] = []
        where: list[str] = []
        if workspace_id and workspace_id != "*":
            where.append("t.workspace_id = ?")
            params.append(workspace_id)
        if since:
            where.append("m.started_at >= ?")
            params.append(since)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        row = self._db.connection.execute(
            f"SELECT AVG(m.latency_ms) AS avg_lat FROM model_calls m"
            f" JOIN traces t ON m.trace_id = t.id"
            f" {where_sql}",
            params,
        ).fetchone()
        return float(row["avg_lat"]) if row and row["avg_lat"] is not None else 0.0

    def count_tool_calls(
        self, since: str = "", workspace_id: str = "default"
    ) -> int:
        params: list[object] = []
        where: list[str] = []
        if workspace_id and workspace_id != "*":
            where.append("t.workspace_id = ?")
            params.append(workspace_id)
        if since:
            where.append("tc.started_at >= ?")
            params.append(since)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM tool_calls tc"
            f" JOIN traces t ON tc.trace_id = t.id"
            f" {where_sql}",
            params,
        ).fetchone()
        return row["cnt"] if row else 0
