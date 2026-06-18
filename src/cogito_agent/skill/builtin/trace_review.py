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

TRACE_REVIEW_MANIFEST = SkillManifest(
    name="trace_review",
    version="1.0.0",
    description="Analyze traces for failures, denied calls, slow/high-cost calls, delivery errors.",
    inputs={},
    outputs={
        "health_report": "Health report: top issues, trace IDs, risk level, recommended fixes",
    },
    steps=[],
    risk_level=SkillRiskLevel.low,
    owner="built-in",
)


def run_trace_review(
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
            root_event_id="skill_trace_review",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "trace_review_analyze", SpanKind.runtime)

    issues: list[dict[str, object]] = []
    try:
        failed_traces = db.connection.execute(
            "SELECT * FROM traces WHERE workspace_id = ?"
            " AND status IN ('failed', 'denied', 'budget_exceeded')"
            " ORDER BY started_at DESC LIMIT 20",
            (workspace_id,),
        ).fetchall()
        for t_raw in failed_traces:
            t = dict(t_raw)
            issues.append({
                "type": "failed_trace",
                "trace_id": str(t["id"]),
                "status": str(t.get("status", "")),
                "started_at": str(t.get("started_at", "")),
                "risk_level": "high" if str(t.get("status", "")) == "failed" else "medium",
                "recommended_fix": "Check model provider or tool availability",
            })

        denied_calls = db.connection.execute(
            "SELECT * FROM tool_calls tc"
            " JOIN traces t ON tc.trace_id = t.id"
            " WHERE t.workspace_id = ? AND tc.decision = 'deny'"
            " ORDER BY tc.latency_ms DESC LIMIT 20",
            (workspace_id,),
        ).fetchall()
        for dc_raw in denied_calls:
            dc = dict(dc_raw)
            issues.append({
                "type": "denied_tool_call",
                "trace_id": str(dc.get("trace_id", "")),
                "capability": str(dc.get("capability_name", "")),
                "risk_level": "low",
                "recommended_fix": "Review policy rules for denied capability",
            })

        unresolved_approvals = db.connection.execute(
            "SELECT * FROM approval_records WHERE workspace_id = ?"
            " AND status = 'pending' ORDER BY created_at DESC LIMIT 20",
            (workspace_id,),
        ).fetchall()
        for ap_raw in unresolved_approvals:
            ap = dict(ap_raw)
            issues.append({
                "type": "unresolved_approval",
                "approval_id": str(ap["id"]),
                "capability": str(ap.get("capability_name", "")),
                "risk_level": "medium",
                "recommended_fix": "Review and resolve pending approval",
            })

        slow_calls = db.connection.execute(
            "SELECT * FROM tool_calls tc"
            " JOIN traces t ON tc.trace_id = t.id"
            " WHERE t.workspace_id = ? AND tc.latency_ms > 10000"
            " ORDER BY tc.latency_ms DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        for sc_raw in slow_calls:
            sc = dict(sc_raw)
            issues.append({
                "type": "slow_tool_call",
                "trace_id": str(sc.get("trace_id", "")),
                "capability": str(sc.get("capability_name", "")),
                "latency_ms": int(str(sc.get("latency_ms", 0))),
                "risk_level": "low",
                "recommended_fix": "Check tool response time or reduce timeout",
            })

        high_cost_model_calls = db.connection.execute(
            "SELECT * FROM model_calls mc"
            " JOIN traces t ON mc.trace_id = t.id"
            " WHERE t.workspace_id = ? AND mc.latency_ms > 30000"
            " ORDER BY mc.latency_ms DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        for hc_raw in high_cost_model_calls:
            hc = dict(hc_raw)
            issues.append({
                "type": "high_cost_model_call",
                "trace_id": str(hc.get("trace_id", "")),
                "provider": str(hc.get("provider", "")),
                "input_tokens": int(str(hc.get("input_token_count", 0))),
                "output_tokens": int(str(hc.get("output_token_count", 0))),
                "latency_ms": int(str(hc.get("latency_ms", 0))),
                "risk_level": "medium",
                "recommended_fix": "Reduce prompt length or switch model",
            })

        dead_letters = db.connection.execute(
            "SELECT * FROM outbox_messages WHERE workspace_id = ?"
            " AND status = 'dead_letter' ORDER BY updated_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        for dl_raw in dead_letters:
            dl = dict(dl_raw)
            issues.append({
                "type": "dead_letter",
                "message_id": str(dl["id"]),
                "last_error": str(dl.get("last_error", "")),
                "risk_level": "high",
                "recommended_fix": "Retry dead-letter messages or investigate delivery adapter",
            })

        file_errors = db.connection.execute(
            "SELECT * FROM workspace_files WHERE workspace_id = ?"
            " AND status = 'error' ORDER BY updated_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        for fe_raw in file_errors:
            fe = dict(fe_raw)
            issues.append({
                "type": "file_ingestion_error",
                "file_name": str(fe.get("file_name", "")),
                "error_message": str(fe.get("error_message", "")),
                "risk_level": "low",
                "recommended_fix": "Re-scan the workspace root",
            })

        skill_failures = db.connection.execute(
            "SELECT * FROM skill_run_logs WHERE workspace_id = ?"
            " AND status IN ('failed', 'rolled_back')"
            " ORDER BY created_at DESC LIMIT 10",
            (workspace_id,),
        ).fetchall()
        for sf_raw in skill_failures:
            sf = dict(sf_raw)
            issues.append({
                "type": "skill_failure",
                "skill_name": str(sf.get("skill_name", "")),
                "trace_id": str(sf.get("trace_id", "")),
                "risk_level": "medium",
                "recommended_fix": f"Check skill '{sf.get('skill_name', '')}' logs",
            })

        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="trace_review.analyze",
            input_summary=f"analyze traces for workspace {workspace_id}",
            output_summary=f"found {len(issues)} issues",
            decision="allow",
        )
    except Exception:
        tracer.end_span(span)
        raise

    audit.log(
        actor_id="skill",
        action="trace_review.analyze",
        resource="traces/tool_calls/model_calls/approvals/outbox/files/skills",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason=f"Trace review found {len(issues)} issues",
        redact_details=True,
    )

    tracer.end_span(span)

    from cogito_agent.workspace import ArtifactService
    art_svc = ArtifactService(db)
    report_body = _build_health_report(issues)
    artifact = art_svc.create_artifact(
        workspace_id=workspace_id,
        source_type="skill",
        source_id="trace_review",
        title=f"Trace Health Report - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
        artifact_type="report",
        mime_type="text/markdown",
        content=report_body,
        created_by="skill:trace_review",
        trace_id=trace_id,
    )

    audit.log(
        actor_id="skill",
        action="artifact.create",
        resource=f"artifact:{artifact['id']}",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="trace_review health report artifact",
        redact_details=True,
    )

    _inbox_notify(db, workspace_id, trace_id, artifact, len(issues))

    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        "artifact_id": artifact.get("id"),
        "issues": issues,
        "issue_count": len(issues),
        "risk_level": _overall_risk(issues),
    }


def _build_health_report(issues: list[dict[str, object]]) -> str:
    lines: list[str] = []
    lines.append("# Trace Health Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"**Total Issues:** {len(issues)}")
    lines.append(f"**Overall Risk:** {_overall_risk(issues)}")
    lines.append("")

    by_type: dict[str, list[dict[str, object]]] = {}
    for issue in issues:
        t = str(issue.get("type", "unknown"))
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(issue)

    for issue_type, type_issues in sorted(by_type.items()):
        lines.append(f"## {issue_type.replace('_', ' ').title()} ({len(type_issues)})")
        lines.append("")
        for iss in type_issues[:5]:
            tid = iss.get("trace_id") or iss.get("approval_id") or ""
            fix = str(iss.get("recommended_fix", ""))
            risk = str(iss.get("risk_level", "unknown"))
            lines.append(f"- **[{risk}]** {tid}: {fix}")
            if "latency_ms" in iss:
                lines[-1] += f" ({iss['latency_ms']}ms)"
        lines.append("")
    return "\n".join(lines)


def _overall_risk(issues: list[dict[str, object]]) -> str:
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    max_risk = "low"
    for issue in issues:
        r = str(issue.get("risk_level", "low"))
        if risk_order.get(r, 0) > risk_order.get(max_risk, 0):
            max_risk = r
    return max_risk


def _inbox_notify(
    db: Database,
    workspace_id: str,
    trace_id: str,
    artifact: dict[str, object],
    issue_count: int,
) -> None:
    try:
        import uuid
        nid = str(uuid.uuid4())
        title = f"Trace Health Report: {issue_count} issues"
        body = (
            f"Trace review found {issue_count} issues. "
            f"View at /console/artifacts/{artifact.get('id', '')}"
        )
        db.connection.execute(
            "INSERT INTO inbox_items"
            " (id, workspace_id, title, body, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, 'skill.trace_review', ?, datetime('now'))",
            (nid, workspace_id, title, body, trace_id),
        )
        db.connection.commit()
    except Exception:
        pass
