from __future__ import annotations

from datetime import UTC, datetime

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.shared import SpanKind
from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer

PROJECT_STATUS_MANIFEST = SkillManifest(
    name="project_status",
    version="1.0.0",
    description="Generate a project status report from memories, sessions, inbox, and file chunks.",
    inputs={},
    outputs={"report": "Markdown report artifact"},
    steps=[
        SkillStep(
            id="collect",
            name="Collect project data",
            kind=StepKind.capability,
            uses_capability="workspace.file.search",
            input_mapping={"query": "project status recent changes"},
        ),
    ],
    risk_level=SkillRiskLevel.medium,
    owner="built-in",
)

BUILTIN_SKILL_MANIFESTS: list[SkillManifest] = [
    PROJECT_STATUS_MANIFEST,
]


def run_project_status(
    db: Database,
    workspace_id: str = "default",
    session_id: str = "",
    trace_id: str = "",
) -> dict[str, object]:
    tracer = Tracer(db)
    audit = AuditLogger(db)

    if not trace_id:
        trace = tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id="skill_project_status",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "project_status_collect", SpanKind.runtime)

    memory_sources: list[dict[str, object]] = []
    session_sources: list[dict[str, object]] = []
    file_chunk_sources: list[dict[str, object]] = []
    inbox_sources: list[dict[str, object]] = []
    task_memories: list[dict[str, object]] = []

    try:
        memories = db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 20",
            (workspace_id,),
        ).fetchall()
        memory_sources = [dict(r) for r in memories]
        task_types = ("task", "project", "general")
        task_memories = [m for m in memory_sources if m.get("type") in task_types]

        sessions = db.connection.execute(
            "SELECT * FROM sessions WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        session_sources = [dict(r) for r in sessions]

        inbox = db.connection.execute(
            "SELECT * FROM inbox_items WHERE workspace_id = ?"
            " AND read_at IS NULL ORDER BY created_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        inbox_sources = [dict(r) for r in inbox]

        file_chunks = db.connection.execute(
            "SELECT fc.*, wf.file_name, wf.relative_path"
            " FROM file_chunks fc"
            " JOIN workspace_files wf ON wf.id = fc.workspace_file_id"
            " WHERE fc.workspace_id = ? AND wf.status = 'active'"
            " ORDER BY fc.created_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        file_chunk_sources = [dict(r) for r in file_chunks]

        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="workspace.file.search",
            input_summary="project status recent changes",
            output_summary=f"collected {len(memory_sources)} memories, "
            f"{len(session_sources)} sessions, "
            f"{len(file_chunk_sources)} file chunks",
            decision="allow",
        )
    except Exception:
        tracer.end_span(span)
        raise

    audit.log(
        actor_id="skill",
        action="workspace.file.read",
        resource="memories/sessions/inbox/file_chunks",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="project_status data collection",
        redact_details=True,
    )

    tracer.end_span(span)

    report = _build_report(
        memory_sources=memory_sources,
        session_sources=session_sources,
        task_memories=task_memories,
        inbox_sources=inbox_sources,
        file_chunk_sources=file_chunk_sources,
    )

    from cogito_agent.workspace import ArtifactService

    art_svc = ArtifactService(db)
    artifact = art_svc.create_artifact(
        workspace_id=workspace_id,
        source_type="skill",
        source_id="project_status",
        title=f"Project Status Report - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
        artifact_type="report",
        mime_type="text/markdown",
        content=report,
        created_by="skill:project_status",
        trace_id=trace_id,
    )

    audit.log(
        actor_id="skill",
        action="artifact.create",
        resource=f"artifact:{artifact['id']}",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="project_status report artifact created",
        redact_details=True,
    )

    _create_inbox_notification(db, workspace_id, trace_id, artifact)

    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        "artifact_id": artifact.get("id"),
        "report": report,
        "memory_count": len(memory_sources),
        "session_count": len(session_sources),
        "file_chunk_count": len(file_chunk_sources),
        "inbox_count": len(inbox_sources),
    }


def _build_report(
    memory_sources: list[dict[str, object]],
    session_sources: list[dict[str, object]],
    task_memories: list[dict[str, object]],
    inbox_sources: list[dict[str, object]],
    file_chunk_sources: list[dict[str, object]],
) -> str:
    lines: list[str] = []
    lines.append("# Project Status Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Tasks
    lines.append("## Current Tasks")
    lines.append("")
    if task_memories:
        for m in task_memories:
            text = str(m.get("text", ""))[:200]
            status = "active"
            if m.get("archived_at"):
                status = "archived"
            lines.append(f"- **{m.get('type', 'task')}** [{status}]: {text}")
    else:
        lines.append("*No task memories found.*")
    lines.append("")

    # Recent sessions
    lines.append("## Recent Sessions")
    lines.append("")
    if session_sources:
        for s in session_sources[:5]:
            title = str(s.get("title", "Untitled"))[:80]
            updated = str(s.get("updated_at", ""))[:10]
            lines.append(f"- **{title}** (last activity: {updated})")
    else:
        lines.append("*No recent sessions.*")
    lines.append("")

    # Inbox items
    lines.append("## Pending Inbox Items")
    lines.append("")
    if inbox_sources:
        for item in inbox_sources[:5]:
            title = str(item.get("title", str(item.get("body", ""))))[:80]
            created = str(item.get("created_at", ""))[:10]
            lines.append(f"- {title} ({created})")
    else:
        lines.append("*No pending inbox items.*")
    lines.append("")

    # File chunks context
    lines.append("## Recent File Context")
    lines.append("")
    if file_chunk_sources:
        for fc in file_chunk_sources[:5]:
            fname = fc.get("file_name", "unknown")
            path = fc.get("relative_path", "")
            text = str(fc.get("text", ""))[:100]
            lines.append(f"- **{fname}** (`{path}`): {text}")
    else:
        lines.append("*No file chunks indexed.*")
    lines.append("")

    # Risks and blockers
    lines.append("## Risks & Blockers")
    lines.append("")
    blockers = [
        m
        for m in memory_sources
        if "block" in str(m.get("text", "")).lower()
        or "risk" in str(m.get("text", "")).lower()
        or "issue" in str(m.get("text", "")).lower()
    ]
    if blockers:
        for b in blockers[:3]:
            lines.append(f"- ⚠️ {str(b.get('text', ''))[:200]}")
    else:
        lines.append("*No blockers identified.*")
    lines.append("")

    # Next steps
    lines.append("## Recommended Next Steps")
    lines.append("")
    lines.append("1. Review pending inbox items and resolve open tasks.")
    lines.append("2. Check recent sessions for incomplete conversations.")
    lines.append("3. Index workspace files for richer context.")
    lines.append("4. Run `project_status` again after changes.")
    lines.append("")

    return "\n".join(lines)


def _create_inbox_notification(
    db: Database,
    workspace_id: str,
    trace_id: str,
    artifact: dict[str, object],
) -> None:
    try:
        import uuid as _uuid

        nid = str(_uuid.uuid4())
        title = f"Project Status Report: {artifact.get('title', '')}"
        body = (
            "A new project status report has been generated. "
            f"View it at /console/artifacts/{artifact.get('id', '')}"
        )
        db.connection.execute(
            "INSERT INTO inbox_items"
            " (id, workspace_id, title, body, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, 'skill.project_status', ?, datetime('now'))",
            (nid, workspace_id, title, body, trace_id),
        )
        db.connection.commit()
    except Exception:
        pass
