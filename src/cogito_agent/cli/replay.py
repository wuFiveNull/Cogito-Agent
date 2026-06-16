from __future__ import annotations

from cogito_agent.storage import Database
from cogito_agent.trace import RedactionHelper


class TraceInspector:
    def __init__(self, db: Database, redactor: RedactionHelper | None = None) -> None:
        self._db = db
        self._redactor = redactor or RedactionHelper()

    def list_traces(
        self, workspace_id: str, limit: int = 50, offset: int = 0,
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT id, workspace_id, session_id, root_event_id,"
            " status, started_at, ended_at"
            " FROM traces WHERE workspace_id = ?"
            " ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_trace_full(self, trace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (trace_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        trace = dict(row)

        trace["spans"] = self._get_spans(trace_id)
        trace["model_calls"] = self._get_model_calls(trace_id)
        trace["tool_calls"] = self._get_tool_calls(trace_id)
        trace["audit_logs"] = self._get_audit_logs(trace_id)
        trace["source_lineage"] = self._get_source_lineage(trace_id)
        trace["context_items"] = self._get_context_items(trace_id)
        trace["state_path"] = self._reconstruct_state_path(trace_id)

        return trace

    def _get_spans(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at",
            (trace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def _get_model_calls(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM model_calls WHERE trace_id = ? ORDER BY rowid",
            (trace_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            if isinstance(r.get("prompt_summary"), str):
                r["prompt_summary"] = self._redactor.redact(r["prompt_summary"])
            if isinstance(r.get("response_summary"), str):
                r["response_summary"] = self._redactor.redact(r["response_summary"])
        return rows

    def _get_tool_calls(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM tool_calls WHERE trace_id = ? ORDER BY rowid",
            (trace_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            if isinstance(r.get("input_summary"), str):
                r["input_summary"] = self._redactor.redact(r["input_summary"])
            if isinstance(r.get("output_summary"), str):
                r["output_summary"] = self._redactor.redact(r["output_summary"])
        return rows

    def _get_audit_logs(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM audit_logs WHERE trace_id = ? ORDER BY rowid",
            (trace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def _get_source_lineage(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM source_lineage WHERE trace_id = ? ORDER BY rowid",
            (trace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def _get_context_items(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM context_items WHERE trace_id = ? ORDER BY rank",
            (trace_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def _reconstruct_state_path(self, trace_id: str) -> list[dict[str, object]]:
        """Reconstruct the state transition path from spans and events."""
        path: list[dict[str, object]] = []
        spans = self._get_spans(trace_id)
        for s in spans:
            kind = str(s.get("kind", ""))
            name = str(s.get("name", ""))
            path.append({
                "span_id": s.get("id"),
                "name": name,
                "kind": kind,
                "status": s.get("status"),
                "started_at": s.get("started_at"),
                "ended_at": s.get("ended_at"),
            })
        return path

    def format_trace_card(self, trace: dict[str, object]) -> str:
        lines: list[str] = []
        lines.append(f"Trace: {trace.get('id', '')}")
        lines.append(f"  Status: {trace.get('status', '')}")
        lines.append(f"  Session: {trace.get('session_id', '') or 'N/A'}")
        lines.append(f"  Started: {trace.get('started_at', '')}")
        ended = trace.get("ended_at")
        if ended:
            lines.append(f"  Ended:   {ended}")
        spans = trace.get("spans", [])
        if isinstance(spans, list):
            lines.append(f"  Spans: {len(spans)}")
        mcs = trace.get("model_calls", [])
        if isinstance(mcs, list):
            lines.append(f"  Model calls: {len(mcs)}")
        tcs = trace.get("tool_calls", [])
        if isinstance(tcs, list):
            lines.append(f"  Tool calls: {len(tcs)}")
        return "\n".join(lines)

    def format_trace_detail(self, trace: dict[str, object]) -> str:
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append(f"Trace: {trace.get('id', '')}")
        lines.append(f"  Status:   {trace.get('status', '')}")
        lines.append(f"  Session:  {trace.get('session_id', '') or 'N/A'}")
        lines.append(f"  Workspace: {trace.get('workspace_id', '')}")
        lines.append(f"  Started:  {trace.get('started_at', '')}")
        ended = trace.get("ended_at")
        if ended:
            lines.append(f"  Ended:    {ended}")

        # State path (reconstructed from spans)
        sp = trace.get("state_path", [])
        if isinstance(sp, list) and sp:
            lines.append("")
            lines.append("-- State Path --")
            for s in sp:
                kind = s.get("kind", "")
                name = s.get("name", "")
                status = s.get("status", "")
                lines.append(f"  [{kind}] {name} -> {status}")

        # Model calls
        mcs = trace.get("model_calls", [])
        if isinstance(mcs, list) and mcs:
            lines.append("")
            lines.append(f"-- Model Calls ({len(mcs)}) --")
            for mc in mcs:
                prov = mc.get("provider", "")
                model = mc.get("model", "")
                tin = mc.get("input_token_count", 0)
                tout = mc.get("output_token_count", 0)
                lat = mc.get("latency_ms", 0)
                err = mc.get("error")
                ps = str(mc.get("prompt_summary", ""))[:60]
                rs = str(mc.get("response_summary", ""))[:60]
                label = f"  {prov}/{model} ({tin}in/{tout}out, {lat}ms)"
                if err:
                    lines.append(f"  \u2716 {label}: {err}")
                else:
                    lines.append(f"  \u2713 {label}")
                    if ps:
                        lines.append(f"      prompt: {ps}...")
                    if rs:
                        lines.append(f"      response: {rs}...")

        # Tool calls
        tcs = trace.get("tool_calls", [])
        if isinstance(tcs, list) and tcs:
            lines.append("")
            lines.append(f"-- Tool Calls ({len(tcs)}) --")
            for tc in tcs:
                cap = tc.get("capability_name", "")
                dec = tc.get("decision", "")
                status = tc.get("status", "")
                lat = tc.get("latency_ms", 0)
                err = tc.get("error")
                label = f"  {cap} (decision={dec}, status={status}, {lat}ms)"
                if err:
                    lines.append(f"  \u2716 {label}: {err}")
                else:
                    lines.append(f"  \u2713 {label}")

        # Audit logs
        als = trace.get("audit_logs", [])
        if isinstance(als, list) and als:
            lines.append("")
            lines.append(f"-- Policy Decisions ({len(als)}) --")
            for a in als:
                act = a.get("action", "")
                res = a.get("resource", "")
                dec = a.get("decision", "")
                reason = a.get("reason", "")
                lines.append(f"  {act} on {res} -> {dec}")
                if reason:
                    lines.append(f"    reason: {reason}")

        # Source lineage
        sls = trace.get("source_lineage", [])
        if isinstance(sls, list) and sls:
            lines.append("")
            lines.append(f"-- Source Lineage ({len(sls)}) --")
            for sl in sls:
                st = sl.get("source_type", "")
                sid = sl.get("source_id", "")
                note = sl.get("note", "")
                lines.append(f"  [{st}] {sid}")
                if note:
                    lines.append(f"    note: {note}")

        lines.append("=" * 60)
        return "\n".join(lines)
