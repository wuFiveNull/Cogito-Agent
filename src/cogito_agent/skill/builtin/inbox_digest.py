from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.shared import SpanKind
from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
)
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer

INBOX_DIGEST_MANIFEST = SkillManifest(
    name="inbox_digest",
    version="1.0.0",
    description="Aggregate unread inbox items, merge duplicates, identify noisy sources.",
    inputs={},
    outputs={
        "digest": "Aggregated digest of unread inbox items with recommendations",
    },
    steps=[],
    risk_level=SkillRiskLevel.low,
    owner="built-in",
)


def run_inbox_digest(
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
            root_event_id="skill_inbox_digest",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "inbox_digest_aggregate", SpanKind.runtime)

    try:
        unread_items = db.connection.execute(
            "SELECT * FROM inbox_items WHERE workspace_id = ?"
            " AND read_at IS NULL ORDER BY created_at ASC",
            (workspace_id,),
        ).fetchall()
        items = [dict(r) for r in unread_items]

        merged = _merge_duplicates(items)
        noisy_sources = _identify_noisy_sources(items)
        recommendations = _generate_recommendations(items, noisy_sources)

        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="inbox_digest.aggregate",
            input_summary=f"aggregated {len(items)} unread items",
            output_summary=(
                f"merged {len(items)} to {len(merged)} groups, {len(noisy_sources)} noisy sources"
            ),
            decision="allow",
        )
    except Exception:
        tracer.end_span(span)
        raise

    audit.log(
        actor_id="skill",
        action="inbox_digest.aggregate",
        resource="inbox_items",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason=f"Inbox digest aggregated {len(items)} items into {len(merged)} groups",
        redact_details=True,
    )

    tracer.end_span(span)

    from cogito_agent.workspace import ArtifactService

    art_svc = ArtifactService(db)
    report_body = _build_digest_report(items, merged, noisy_sources, recommendations)
    artifact = art_svc.create_artifact(
        workspace_id=workspace_id,
        source_type="skill",
        source_id="inbox_digest",
        title=f"Inbox Digest - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
        artifact_type="report",
        mime_type="text/markdown",
        content=report_body,
        created_by="skill:inbox_digest",
        trace_id=trace_id,
    )

    audit.log(
        actor_id="skill",
        action="artifact.create",
        resource=f"artifact:{artifact['id']}",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="inbox_digest artifact",
        redact_details=True,
    )

    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        "artifact_id": artifact.get("id"),
        "item_count": len(items),
        "merged_groups": len(merged),
        "noisy_sources": noisy_sources,
        "recommendations": recommendations,
        "summary": f"Digested {len(items)} items into {len(merged)} groups, "
        f"{len(noisy_sources)} noisy sources identified",
    }


def _merge_duplicates(
    items: list[dict[str, object]],
) -> list[dict[str, list[dict[str, object]]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for item in items:
        key = _normalize_key(item)
        if key not in groups:
            groups[key] = []
        groups[key].append(item)

    merged_result: list[dict[str, Any]] = []
    for key, group in groups.items():
        merged_result.append({"key": key, "items": group, "count": len(group)})
    return merged_result


def _normalize_key(item: dict[str, object]) -> str:
    title = str(item.get("title", "")).strip().lower()
    body = str(item.get("body", "")).strip().lower()
    source = str(item.get("source", "")).strip().lower()
    combined = f"{source}:{title[:40]}:{body[:60]}"
    return combined


def _identify_noisy_sources(
    items: list[dict[str, object]],
) -> list[dict[str, object]]:
    source_counts: Counter[str] = Counter()
    for item in items:
        source = str(item.get("source", "unknown"))
        source_counts[source] += 1

    total = len(items) or 1
    noisy: list[dict[str, object]] = []
    for source, count in source_counts.most_common():
        ratio = count / total
        if ratio > 0.3 and count >= 3:
            noisy.append(
                {
                    "source": source,
                    "count": count,
                    "ratio": round(ratio, 2),
                    "suggestion": "reduce_frequency",
                }
            )
    return noisy


def _generate_recommendations(
    items: list[dict[str, object]],
    noisy_sources: list[dict[str, object]],
) -> list[dict[str, object]]:
    recs: list[dict[str, object]] = []
    if not items:
        recs.append({"action": "none", "reason": "No unread items"})
        return recs

    for item in items:
        recs.append(
            {
                "action": "keep",
                "item_id": str(item.get("id", "")),
                "title": str(item.get("title", ""))[:80],
            }
        )

    for ns in noisy_sources:
        recs.append(
            {
                "action": "reduce_frequency",
                "source": str(ns.get("source", "")),
                "reason": (
                    f"Source '{ns['source']}' accounts for "
                    f"{float(str(ns.get('ratio', 0))) * 100:.0f}% of all items"
                ),
            }
        )

    return recs


def _build_digest_report(
    items: list[dict[str, object]],
    merged: list[dict[str, list[dict[str, object]]]],
    noisy_sources: list[dict[str, object]],
    recommendations: list[dict[str, object]],
) -> str:
    lines: list[str] = []
    lines.append("# Inbox Digest")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"**Unread Items:** {len(items)}")
    lines.append(f"**Merged Groups:** {len(merged)}")
    lines.append(f"**Noisy Sources:** {len(noisy_sources)}")
    lines.append("")

    if merged:
        lines.append("## Groups")
        lines.append("")
        for g in merged[:10]:
            count = g["count"]
            sample = g["items"][0] if g["items"] else {}
            title = str(sample.get("title", "Untitled"))[:80]
            lines.append(f"- **{title}** ({count} items)")
    else:
        lines.append("*No items to digest.*")
    lines.append("")

    if noisy_sources:
        lines.append("## Noisy Sources")
        lines.append("")
        for ns in noisy_sources:
            ratio_val = float(str(ns.get("ratio", 0)))
            lines.append(f"- **{ns['source']}**: {ns['count']} items ({ratio_val * 100:.0f}%)")
            lines.append(f"  - Suggestion: {ns['suggestion']}")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    if recommendations:
        for r in recommendations:
            action = r.get("action", "keep")
            reason = str(r.get("reason", ""))[:100]
            lines.append(f"- **{action}**: {reason}")
    else:
        lines.append("*No recommendations.*")

    return "\n".join(lines)
