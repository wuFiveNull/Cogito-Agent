from __future__ import annotations

from datetime import UTC, datetime

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.shared import SpanKind
from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
)
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer

TASK_EXTRACTION_MANIFEST = SkillManifest(
    name="task_extraction",
    version="1.0.0",
    description="Extract task candidates from sessions, memories, inbox, files, and artifacts.",
    inputs={},
    outputs={
        "candidates": "Task candidates with title, description, source, priority, confidence",
    },
    steps=[],
    risk_level=SkillRiskLevel.medium,
    owner="built-in",
)


def run_task_extraction(
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
            root_event_id="skill_task_extraction",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "task_extraction_collect", SpanKind.runtime)

    candidates: list[dict[str, object]] = []
    try:
        recent_sessions = db.connection.execute(
            "SELECT * FROM sessions WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 5",
            (workspace_id,),
        ).fetchall()

        for s_raw in recent_sessions:
            s = dict(s_raw)
            title = str(s.get("title", ""))
            if title and title not in ("Console Chat", ""):
                candidates.append({
                    "title": f"Follow up: {title[:80]}",
                    "description": f"Session '{title}' may need follow-up",
                    "source": "session",
                    "source_id": str(s["id"]),
                    "due_date": "",
                    "priority": "normal",
                    "confidence": 0.5,
                    "requires_confirmation": True,
                })

        recent_memories = db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL AND type IN ('task', 'project')"
            " ORDER BY updated_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()

        for m_raw in recent_memories:
            m = dict(m_raw)
            text = str(m.get("text", ""))
            status = str(m.get("status", ""))
            if status in ("active", "") and len(text) > 20:
                candidates.append({
                    "title": f"Review task: {text[:80]}",
                    "description": text[:200],
                    "source": "memory",
                    "source_id": str(m["id"]),
                    "due_date": str(m.get("created_at", ""))[:10],
                    "priority": "normal",
                    "confidence": 0.6,
                    "requires_confirmation": True,
                })

        pending_inbox = db.connection.execute(
            "SELECT * FROM inbox_items WHERE workspace_id = ?"
            " AND read_at IS NULL ORDER BY created_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()

        for item_raw in pending_inbox:
            item = dict(item_raw)
            title = str(item.get("title", "Untitled inbox item"))[:80]
            candidates.append({
                "title": f"Inbox: {title}",
                "description": str(item.get("body", ""))[:200],
                "source": "inbox",
                "source_id": str(item["id"]),
                "due_date": "",
                "priority": "normal",
                "confidence": 0.7,
                "requires_confirmation": False,
            })

        recent_artifacts = db.connection.execute(
            "SELECT * FROM artifacts WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 5",
            (workspace_id,),
        ).fetchall()

        for art_raw in recent_artifacts:
            art = dict(art_raw)
            title = str(art.get("title", ""))[:80]
            if title:
                candidates.append({
                    "title": f"Review artifact: {title}",
                    "description": f"Artifact from {art.get('source_type', 'unknown')}",
                    "source": "artifact",
                    "source_id": str(art["id"]),
                    "due_date": "",
                    "priority": "low",
                    "confidence": 0.4,
                    "requires_confirmation": True,
                })

        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="task_extraction.collect",
            input_summary="extract task candidates",
            output_summary=f"found {len(candidates)} candidates",
            decision="allow",
        )
    except Exception:
        tracer.end_span(span)
        raise

    audit.log(
        actor_id="skill",
        action="task_extraction.extract",
        resource="sessions/memories/inbox/artifacts",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason=f"Extracted {len(candidates)} task candidates",
        redact_details=True,
    )

    tracer.end_span(span)

    from cogito_agent.workspace import ArtifactService
    art_svc = ArtifactService(db)
    import json
    proposal_json = json.dumps({"candidates": candidates}, indent=2, default=str)
    artifact = art_svc.create_artifact(
        workspace_id=workspace_id,
        source_type="skill",
        source_id="task_extraction",
        title=f"Task Extraction Candidates - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
        artifact_type="json",
        mime_type="application/json",
        content=proposal_json,
        created_by="skill:task_extraction",
        trace_id=trace_id,
    )

    audit.log(
        actor_id="skill",
        action="artifact.create",
        resource=f"artifact:{artifact['id']}",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="task_extraction candidates artifact",
        redact_details=True,
    )

    _inbox_notify(db, workspace_id, trace_id, artifact, len(candidates))

    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        "artifact_id": artifact.get("id"),
        "candidates": candidates,
        "candidate_count": len(candidates),
    }


def _inbox_notify(
    db: Database,
    workspace_id: str,
    trace_id: str,
    artifact: dict[str, object],
    candidate_count: int,
) -> None:
    try:
        import uuid
        nid = str(uuid.uuid4())
        title = f"Task Extraction: {candidate_count} candidates"
        body = (
            f"Task extraction found {candidate_count} candidates. "
            f"View at /console/artifacts/{artifact.get('id', '')}"
        )
        db.connection.execute(
            "INSERT INTO inbox_items"
            " (id, workspace_id, title, body, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, 'skill.task_extraction', ?, datetime('now'))",
            (nid, workspace_id, title, body, trace_id),
        )
        db.connection.commit()
    except Exception:
        pass
