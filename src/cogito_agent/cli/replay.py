from __future__ import annotations

from cogito_agent.storage import Database
from cogito_agent.trace import RedactionHelper


class TraceInspector:
    def __init__(self, db: Database, redactor: RedactionHelper | None = None) -> None:
        self._db = db
        self._redactor = redactor or RedactionHelper()
        from cogito_agent.storage.repositories import (
            ModelCallRepository,
            ToolCallRepository,
            TraceRepository,
        )
        self._traces = TraceRepository(db)
        self._model_calls = ModelCallRepository(db)
        self._tool_calls = ToolCallRepository(db)

    def list_traces(
        self,
        workspace_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        return self._traces.list_by_workspace(workspace_id, limit=limit, offset=offset)

    def get_trace_full(self, trace_id: str) -> dict[str, object] | None:
        detail = self._traces.get_detail_with_spans(trace_id)
        if detail is None:
            return None

        detail["source_lineage"] = self._traces.get_source_lineage_by_trace(trace_id)
        detail["context_items"] = self._traces.get_context_items_by_trace(trace_id)
        detail["state_path"] = self._reconstruct_state_path(trace_id)
        detail["skill_runs"] = self._get_skill_run_logs(trace_id)

        return detail

    def _get_skill_run_logs(self, trace_id: str) -> list[dict[str, object]]:
        from cogito_agent.skill import SkillRunner
        return SkillRunner(self._db).list_skill_run_logs_by_trace(trace_id)

    def _reconstruct_state_path(self, trace_id: str) -> list[dict[str, object]]:
        """Reconstruct the state transition path from spans and events."""
        path: list[dict[str, object]] = []
        spans = self._traces.get_spans_by_trace(trace_id)
        for s in spans:
            kind = str(s.get("kind", ""))
            name = str(s.get("name", ""))
            path.append(
                {
                    "span_id": s.get("id"),
                    "name": name,
                    "kind": kind,
                    "status": s.get("status"),
                    "started_at": s.get("started_at"),
                    "ended_at": s.get("ended_at"),
                }
            )
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

        # Audit logs (from get_detail_with_spans -> key is "audits")
        als = trace.get("audits", trace.get("audit_logs", []))
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

        # Skill runs
        skills = trace.get("skill_runs", [])
        if isinstance(skills, list) and skills:
            lines.append("")
            lines.append(f"-- Skill Runs ({len(skills)}) --")
            for sk in skills:
                sname = sk.get("skill_name", "")
                sstatus = sk.get("status", "")
                created = str(sk.get("created_at", ""))[:19]
                lines.append(f"  {sname} [{sstatus}] {created}")
                steps = sk.get("steps", [])
                if isinstance(steps, list):
                    for sl in steps:
                        sid = sl.get("step_id", "")
                        st = sl.get("status", "")
                        out = str(sl.get("output", ""))[:60]
                        err = sl.get("error", "")
                        if err:
                            lines.append(f"    [{st}] {sid}: {err}")
                        else:
                            lines.append(f"    [{st}] {sid}: {out}")

        lines.append("=" * 60)
        return "\n".join(lines)


def run_trace_replay(action: str, trace_id: str, db_path: str) -> None:
    """CLI entry point for ``cogito replay list/show``."""
    from cogito_agent.storage import Database

    db = Database(db_path)
    db.initialize()
    inspector = TraceInspector(db)

    if action == "list":
        traces = inspector.list_traces(workspace_id="*", limit=100)
        if not traces:
            print("No traces found.")
            return
        print(f"\nTraces ({len(traces)}):")
        for t in traces:
            tid = str(t.get("id", ""))[:16]
            status = str(t.get("status", ""))
            started = str(t.get("started_at", ""))[:19]
            print(f"  {tid}  [{status}]  {started}")

    elif action == "show":
        trace = inspector.get_trace_full(trace_id)
        if trace is None:
            print(f"Trace '{trace_id}' not found.")
            return
        print(inspector.format_trace_detail(trace))

    db.close()
