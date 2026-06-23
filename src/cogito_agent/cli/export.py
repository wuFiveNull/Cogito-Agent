from __future__ import annotations

import json

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    AuditRepository,
    MemoryItemRepository,
    MemoryRepository,
    ModelCallRepository,
    SessionRepository,
    ToolCallRepository,
    TraceRepository,
    WorkspaceRepository,
    WorkspaceSettingsRepository,
)
from cogito_agent.shared.redaction import RedactionHelper


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

    sess_repo = SessionRepository(db)
    data["sessions"] = sess_repo.list_by_workspace(workspace_id)

    if include_memories:
        try:
            mem_repo = MemoryRepository(db)
            data["memories"] = mem_repo.list_active_or_archived(workspace_id, limit=0)
        except Exception:
            data["memories"] = []

        try:
            mi_repo = MemoryItemRepository(db)
            data["memory_candidates"] = mi_repo.list_active_with_filters(workspace_id, limit=50)
        except Exception:
            data["memory_candidates"] = []

    if include_traces:
        trace_repo = TraceRepository(db)
        data["traces"] = trace_repo.list_by_workspace(workspace_id, limit=0)

        data["model_calls"] = ModelCallRepository(db).list_by_workspace(workspace_id)
        data["tool_calls"] = ToolCallRepository(db).list_by_workspace(workspace_id)
        data["spans"] = trace_repo.list_spans_by_workspace(workspace_id)

    if include_audit:
        data["audit_logs"] = AuditRepository(db).list_by_filters(workspace_id=workspace_id, limit=0)

    settings_repo = WorkspaceSettingsRepository(db)
    data["settings"] = settings_repo.get(workspace_id)

    from cogito_agent.skill.storage import WorkspaceSkill
    data["workspace_skills"] = WorkspaceSkill(db).list_by_workspace(workspace_id)

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
