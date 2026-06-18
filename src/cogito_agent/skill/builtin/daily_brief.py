from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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

DAILY_BRIEF_MANIFEST = SkillManifest(
    name="daily_brief",
    version="1.0.0",
    description="Generate a daily briefing from memories, sessions, inbox, artifacts, and files.",
    inputs={
        "date": "Date string in YYYY-MM-DD format",
        "include_memories": "Include recent memories (bool)",
        "include_tasks": "Include task memories (bool)",
        "include_recent_sessions": "Include recent sessions (bool)",
        "include_inbox": "Include pending inbox/outbox items (bool)",
        "include_artifacts": "Include recent artifacts (bool)",
        "include_files": "Include file chunks (bool)",
    },
    outputs={
        "summary": "Briefing summary text",
        "important_items": "List of important items",
        "open_tasks": "List of open tasks",
        "recommended_actions": "Recommended next actions",
        "sources": "Data sources used",
    },
    steps=[
        SkillStep(
            id="collect",
            name="Collect daily data",
            kind=StepKind.capability,
            uses_capability="workspace.file.search",
            input_mapping={"query": "daily brief context"},
        ),
    ],
    risk_level=SkillRiskLevel.medium,
    owner="built-in",
)


def run_daily_brief(
    db: Database,
    workspace_id: str = "default",
    session_id: str = "",
    trace_id: str = "",
    date: str = "",
    include_memories: bool = True,
    include_tasks: bool = True,
    include_recent_sessions: bool = True,
    include_inbox: bool = True,
    include_artifacts: bool = True,
    include_files: bool = True,
) -> dict[str, object]:
    tracer = Tracer(db)
    audit = AuditLogger(db)

    if not trace_id:
        trace = tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id="skill_daily_brief",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "daily_brief_collect", SpanKind.runtime)
    target_date = date or datetime.now(UTC).strftime("%Y-%m-%d")

    collected: dict[str, list[dict[str, object]]] = {
        "memories": [],
        "task_memories": [],
        "sessions": [],
        "inbox_items": [],
        "artifacts": [],
        "file_chunks": [],
    }

    try:
        if include_memories:
            memories_raw = db.connection.execute(
                "SELECT * FROM memories WHERE workspace_id = ?"
                " AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 20",
                (workspace_id,),
            ).fetchall()
            collected["memories"] = [dict(r) for r in memories_raw]

        if include_tasks:
            tasks_raw = db.connection.execute(
                "SELECT * FROM memories WHERE workspace_id = ?"
                " AND deleted_at IS NULL AND type IN ('task', 'project', 'general')"
                " AND status != 'stale'"
                " ORDER BY updated_at DESC LIMIT 20",
                (workspace_id,),
            ).fetchall()
            collected["task_memories"] = [dict(r) for r in tasks_raw]

        if include_recent_sessions:
            sessions_raw = db.connection.execute(
                "SELECT * FROM sessions WHERE workspace_id = ?"
                " AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 10",
                (workspace_id,),
            ).fetchall()
            collected["sessions"] = [dict(r) for r in sessions_raw]

        if include_inbox:
            inbox_raw = db.connection.execute(
                "SELECT * FROM inbox_items WHERE workspace_id = ?"
                " AND read_at IS NULL ORDER BY created_at DESC LIMIT 20",
                (workspace_id,),
            ).fetchall()
            collected["inbox_items"] = [dict(r) for r in inbox_raw]

        if include_artifacts:
            artifacts_raw = db.connection.execute(
                "SELECT * FROM artifacts WHERE workspace_id = ?"
                " AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 10",
                (workspace_id,),
            ).fetchall()
            collected["artifacts"] = [dict(r) for r in artifacts_raw]

        if include_files:
            chunks_raw = db.connection.execute(
                "SELECT fc.*, wf.file_name, wf.relative_path"
                " FROM file_chunks fc"
                " JOIN workspace_files wf ON wf.id = fc.workspace_file_id"
                " WHERE fc.workspace_id = ? AND wf.status = 'active'"
                " ORDER BY fc.created_at DESC LIMIT 10",
                (workspace_id,),
            ).fetchall()
            collected["file_chunks"] = [dict(r) for r in chunks_raw]

        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="daily_brief.collect",
            input_summary=f"date={target_date}",
            output_summary=f"collected {sum(len(v) for v in collected.values())} items",
            decision="allow",
        )
    except Exception:
        tracer.end_span(span)
        raise

    audit.log(
        actor_id="skill",
        action="daily_brief.collect",
        resource="memories/sessions/inbox/artifacts/files",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason=f"daily_brief data collection for {target_date}",
        redact_details=True,
    )

    tracer.end_span(span)

    from cogito_agent.context import ContextEngine
    ctx_engine = ContextEngine()
    ctx_items = ctx_engine.build(
        recent_messages=collected["memories"][:5],
        memories=collected["memories"],
        current_message=f"Generate daily brief for {target_date}",
        db=db,
        trace_id=trace_id,
        workspace_id=workspace_id,
    )

    summary = _build_brief_summary(collected, target_date)
    important_items = _extract_important_items(collected)
    open_tasks = _extract_open_tasks(collected)
    recommended_actions = _generate_recommendations(collected, ctx_items)

    from cogito_agent.workspace import ArtifactService
    art_svc = ArtifactService(db)
    report_body = _format_brief_report(
        target_date, summary, important_items, open_tasks,
        recommended_actions, collected,
    )
    artifact = art_svc.create_artifact(
        workspace_id=workspace_id,
        source_type="skill",
        source_id="daily_brief",
        title=f"Daily Brief - {target_date}",
        artifact_type="report",
        mime_type="text/markdown",
        content=report_body,
        created_by="skill:daily_brief",
        trace_id=trace_id,
    )

    audit.log(
        actor_id="skill",
        action="artifact.create",
        resource=f"artifact:{artifact['id']}",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="daily_brief report artifact",
        redact_details=True,
    )

    _inbox_notify(db, workspace_id, trace_id, artifact, target_date)

    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        "artifact_id": artifact.get("id"),
        "summary": summary,
        "important_items": important_items,
        "open_tasks": open_tasks,
        "recommended_actions": recommended_actions,
        "sources": {k: len(v) for k, v in collected.items()},
    }


def _build_brief_summary(
    collected: dict[str, list[dict[str, object]]],
    target_date: str,
) -> str:
    parts: list[str] = []
    mem_count = len(collected["memories"])
    task_count = len(collected["task_memories"])
    sess_count = len(collected["sessions"])
    inbox_count = len(collected["inbox_items"])
    art_count = len(collected["artifacts"])
    parts.append(f"Daily Brief for {target_date}")
    parts.append(f"Found {mem_count} memories, {task_count} tasks, {sess_count} sessions")
    parts.append(f"{inbox_count} pending inbox items, {art_count} recent artifacts")
    return " | ".join(parts)


def _extract_important_items(
    collected: dict[str, list[dict[str, object]]],
) -> list[str]:
    items: list[str] = []
    for item in collected["inbox_items"][:5]:
        title = str(item.get("title", "Untitled"))[:100]
        items.append(f"Inbox: {title}")
    for m in collected["memories"][:3]:
        text = str(m.get("text", ""))[:100]
        items.append(f"Memory: {text}")
    return items


def _extract_open_tasks(
    collected: dict[str, list[dict[str, object]]],
) -> list[str]:
    tasks: list[str] = []
    for m in collected["task_memories"][:10]:
        text = str(m.get("text", ""))[:120]
        tasks.append(f"{m.get('type', 'task')}: {text}")
    if not tasks:
        tasks.append("No open tasks found")
    return tasks


def _generate_recommendations(
    collected: dict[str, list[dict[str, object]]],
    ctx_items: list[Any],
) -> list[str]:
    recs: list[str] = []
    if collected["inbox_items"]:
        recs.append(f"Review {len(collected['inbox_items'])} pending inbox items")
    if collected["task_memories"]:
        recs.append(f"Check progress on {len(collected['task_memories'])} tasks")
    if collected["sessions"]:
        recs.append("Review recent sessions for follow-ups")
    return recs


def _format_brief_report(
    target_date: str,
    summary: str,
    important_items: list[str],
    open_tasks: list[str],
    recommended_actions: list[str],
    collected: dict[str, list[dict[str, object]]],
) -> str:
    lines: list[str] = []
    lines.append(f"# Daily Brief - {target_date}")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.append("## Important Items")
    lines.append("")
    if important_items:
        for item in important_items:
            lines.append(f"- {item}")
    else:
        lines.append("*No important items.*")
    lines.append("")
    lines.append("## Open Tasks")
    lines.append("")
    if open_tasks:
        for t in open_tasks:
            lines.append(f"- {t}")
    else:
        lines.append("*No open tasks.*")
    lines.append("")
    lines.append("## Recommended Actions")
    lines.append("")
    if recommended_actions:
        for a in recommended_actions:
            lines.append(f"- {a}")
    else:
        lines.append("*No recommendations.*")
    lines.append("")
    lines.append("## Sources Used")
    lines.append("")
    for key, items in collected.items():
        lines.append(f"- {key}: {len(items)} items")
    return "\n".join(lines)


def _inbox_notify(
    db: Database,
    workspace_id: str,
    trace_id: str,
    artifact: dict[str, object],
    target_date: str,
) -> None:
    try:
        import uuid
        nid = str(uuid.uuid4())
        title = f"Daily Brief - {target_date}"
        body = (
            f"A daily brief has been generated for {target_date}. "
            f"View it at /console/artifacts/{artifact.get('id', '')}"
        )
        db.connection.execute(
            "INSERT INTO inbox_items"
            " (id, workspace_id, title, body, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, 'skill.daily_brief', ?, datetime('now'))",
            (nid, workspace_id, title, body, trace_id),
        )
        db.connection.commit()
    except Exception:
        pass
