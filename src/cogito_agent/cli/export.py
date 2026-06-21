from __future__ import annotations

import json

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository
from cogito_agent.trace.redaction import RedactionHelper


def _redact_dict(obj: object, helper: RedactionHelper) -> object:
    if isinstance(obj, dict):
        return {k: _redact_dict(v, helper) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_dict(v, helper) for v in obj]
    if isinstance(obj, str):
        return helper.redact(obj)
    return obj


def export_workspace(
    db: Database,
    workspace_id: str,
    *,
    include_traces: bool = True,
    include_memories: bool = True,
    include_audit: bool = True,
    redact: bool = True,
) -> dict[str, object]:
    ws_repo = WorkspaceRepository(db)
    ws = ws_repo.get_by_id(workspace_id)
    if ws is None:
        raise ValueError(f"Workspace '{workspace_id}' not found")

    data: dict[str, object] = {
        "workspace": dict(ws),
        "sessions": [],
    }

    cur = db.connection.execute(
        "SELECT * FROM sessions WHERE workspace_id = ? AND deleted_at IS NULL",
        (workspace_id,),
    )
    data["sessions"] = [dict(r) for r in cur.fetchall()]

    if include_memories:
        try:
            cur = db.connection.execute(
                "SELECT * FROM memories WHERE workspace_id = ? AND deleted_at IS NULL",
                (workspace_id,),
            )
            data["memories"] = [dict(r) for r in cur.fetchall()]
        except Exception:
            data["memories"] = []

        try:
            rows = db.connection.execute(
                "SELECT id, summary, memory_type, reinforcement FROM memory_items"
                " WHERE workspace_id=? AND status='active' AND memory_type != '_recent_context'"
                " ORDER BY updated_at DESC LIMIT 50",
                (workspace_id,),
            ).fetchall()
            data["memory_candidates"] = [dict(r) for r in rows]
        except Exception:
            data["memory_candidates"] = []

    if include_traces:
        cur = db.connection.execute("SELECT * FROM traces WHERE workspace_id = ?", (workspace_id,))
        data["traces"] = [dict(r) for r in cur.fetchall()]

        cur = db.connection.execute(
            "SELECT * FROM model_calls mc"
            " JOIN traces t ON mc.trace_id = t.id"
            " WHERE t.workspace_id = ?",
            (workspace_id,),
        )
        data["model_calls"] = [dict(r) for r in cur.fetchall()]

        cur = db.connection.execute(
            "SELECT * FROM tool_calls tc"
            " JOIN traces t ON tc.trace_id = t.id"
            " WHERE t.workspace_id = ?",
            (workspace_id,),
        )
        data["tool_calls"] = [dict(r) for r in cur.fetchall()]

        cur = db.connection.execute(
            "SELECT * FROM spans sp JOIN traces t ON sp.trace_id = t.id WHERE t.workspace_id = ?",
            (workspace_id,),
        )
        data["spans"] = [dict(r) for r in cur.fetchall()]

    if include_audit:
        cur = db.connection.execute(
            "SELECT * FROM audit_logs WHERE workspace_id = ?", (workspace_id,)
        )
        data["audit_logs"] = [dict(r) for r in cur.fetchall()]

    cur = db.connection.execute(
        "SELECT * FROM workspace_settings WHERE workspace_id = ?",
        (workspace_id,),
    )
    data["settings"] = [dict(r) for r in cur.fetchall()]

    cur = db.connection.execute(
        "SELECT * FROM workspace_skills WHERE workspace_id = ?",
        (workspace_id,),
    )
    data["workspace_skills"] = [dict(r) for r in cur.fetchall()]

    if redact:
        helper = RedactionHelper()
        redacted = _redact_dict(data, helper)
        if isinstance(redacted, dict):
            data = {k: v for k, v in redacted.items()}

    return data


def format_export(data: dict[str, object], fmt: str = "json") -> str:
    if fmt == "json":
        return json.dumps(data, indent=2, default=str)
    raise ValueError(f"Unsupported format: {fmt}")
