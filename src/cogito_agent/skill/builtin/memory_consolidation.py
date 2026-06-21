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

MEMORY_CONSOLIDATION_MANIFEST = SkillManifest(
    name="memory_consolidation",
    version="1.0.0",
    description="Identify duplicate/stale/conflicting/low-confidence memories, produce proposal.",
    inputs={},
    outputs={
        "proposals": "Consolidation proposals with action, reason, confidence, source ids",
    },
    steps=[],
    risk_level=SkillRiskLevel.medium,
    owner="built-in",
)

PROPOSAL_ACTION_MERGE = "merge"
PROPOSAL_ACTION_ARCHIVE = "archive"
PROPOSAL_ACTION_DELETE = "delete"
PROPOSAL_ACTION_FLAG = "flag"
PROPOSAL_ACTION_REVIEW = "review"


def run_memory_consolidation(
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
            root_event_id="skill_memory_consolidation",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "memory_consolidation_analyze", SpanKind.runtime)

    proposals: list[dict[str, object]] = []
    try:
        all_memories = db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY created_at ASC",
            (workspace_id,),
        ).fetchall()
        memory_list = [dict(r) for r in all_memories]

        proposals.extend(_find_duplicates(memory_list))
        proposals.extend(_find_stale(memory_list))
        proposals.extend(_find_conflicting(memory_list))
        proposals.extend(_find_low_confidence(memory_list))

        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="memory_consolidation.analyze",
            input_summary=f"analyzed {len(memory_list)} memories",
            output_summary=f"found {len(proposals)} proposals",
            decision="allow",
        )
    except Exception:
        tracer.end_span(span)
        raise

    audit.log(
        actor_id="skill",
        action="memory_consolidation.analyze",
        resource="memories",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason=f"Analyzed {len(memory_list)} memories, generated {len(proposals)} proposals",
        redact_details=True,
    )

    tracer.end_span(span)

    from cogito_agent.workspace import ArtifactService

    art_svc = ArtifactService(db)
    proposal_json = _format_proposals_json(proposals)
    artifact = art_svc.create_artifact(
        workspace_id=workspace_id,
        source_type="skill",
        source_id="memory_consolidation",
        title=f"Memory Consolidation Proposal - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
        artifact_type="json",
        mime_type="application/json",
        content=proposal_json,
        created_by="skill:memory_consolidation",
        trace_id=trace_id,
    )

    audit.log(
        actor_id="skill",
        action="artifact.create",
        resource=f"artifact:{artifact['id']}",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason="memory_consolidation proposal artifact",
        redact_details=True,
    )

    _inbox_notify(db, workspace_id, trace_id, artifact, len(proposals))

    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        "artifact_id": artifact.get("id"),
        "proposals": proposals,
        "proposal_count": len(proposals),
        "memory_count": len(memory_list),
        "summary": _build_summary(proposals),
    }


def _find_duplicates(memories: list[dict[str, object]]) -> list[dict[str, object]]:
    proposals: list[dict[str, object]] = []
    seen: dict[str, list[dict[str, object]]] = {}
    for m in memories:
        text = str(m.get("text", "")).strip().lower()
        if not text:
            continue
        if text not in seen:
            seen[text] = [m]
        else:
            seen[text].append(m)

    for text, group in seen.items():
        if len(group) < 2:
            continue
        ids = [str(m["id"]) for m in group]
        proposals.append(
            {
                "action": PROPOSAL_ACTION_MERGE,
                "reason": f"Duplicate memories ({len(group)} copies of same text)",
                "confidence": 0.9,
                "source_memory_ids": ids,
            }
        )
    return proposals


def _find_stale(memories: list[dict[str, object]]) -> list[dict[str, object]]:
    proposals: list[dict[str, object]] = []
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    for m in memories:
        created_str = str(m.get("created_at", ""))
        if not created_str:
            continue
        try:
            created = dt.datetime.fromisoformat(created_str)
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.UTC)
            age_days = (now - created).days
        except (ValueError, TypeError):
            continue
        if age_days >= 30 and m.get("status") != "stale":
            confidence = min(0.9, 0.5 + age_days / 365.0)
            proposals.append(
                {
                    "action": PROPOSAL_ACTION_ARCHIVE,
                    "reason": f"Memory is {age_days} days old without recent updates",
                    "confidence": round(confidence, 2),
                    "source_memory_ids": [str(m["id"])],
                }
            )
    return proposals


def _find_conflicting(memories: list[dict[str, object]]) -> list[dict[str, object]]:
    proposals: list[dict[str, object]] = []
    active = [m for m in memories if m.get("status") in ("active", None)]
    for i, a in enumerate(active):
        for b in active[i + 1 :]:
            text_a = str(a.get("text", "")).lower()
            text_b = str(b.get("text", "")).lower()
            if not text_a or not text_b:
                continue
            if _texts_conflict(text_a, text_b):
                proposals.append(
                    {
                        "action": PROPOSAL_ACTION_REVIEW,
                        "reason": "Conflicting information detected between two memories",
                        "confidence": 0.6,
                        "source_memory_ids": [str(a["id"]), str(b["id"])],
                    }
                )
    return proposals


def _texts_conflict(text_a: str, text_b: str) -> bool:
    negation_words = {"not", "no", "never", "cannot", "isn't", "aren't", "don't", "doesn't"}
    words_a = set(text_a.split())
    words_b = set(text_b.split())
    if not words_a or not words_b:
        return False
    overlap = words_a & words_b
    if len(overlap) < 3:
        return False
    has_neg_a = bool(words_a & negation_words)
    has_neg_b = bool(words_b & negation_words)
    return has_neg_a != has_neg_b


def _find_low_confidence(memories: list[dict[str, object]]) -> list[dict[str, object]]:
    proposals: list[dict[str, object]] = []
    for m in memories:
        confidence = float(str(m.get("confidence", 0.5)))
        if confidence < 0.3:
            proposals.append(
                {
                    "action": PROPOSAL_ACTION_FLAG,
                    "reason": f"Low confidence memory ({confidence:.2f})",
                    "confidence": 1.0 - confidence,
                    "source_memory_ids": [str(m["id"])],
                }
            )
    return proposals


def _format_proposals_json(proposals: list[dict[str, object]]) -> str:
    import json

    data = {"proposals": proposals, "generated_at": datetime.now(UTC).isoformat()}
    return json.dumps(data, indent=2)


def _build_summary(proposals: list[dict[str, object]]) -> str:
    from collections import Counter

    action_counts: Counter[str] = Counter()
    for p in proposals:
        action_counts[str(p.get("action", ""))] += 1
    if not proposals:
        return "No consolidation actions proposed"
    parts = [f"{k}: {v}" for k, v in sorted(action_counts.items())]
    return f"Consolidation proposal: {', '.join(parts)} ({len(proposals)} total)"


def _inbox_notify(
    db: Database,
    workspace_id: str,
    trace_id: str,
    artifact: dict[str, object],
    proposal_count: int,
) -> None:
    try:
        import uuid

        nid = str(uuid.uuid4())
        title = f"Memory Consolidation: {proposal_count} proposals"
        body = (
            f"Memory consolidation generated {proposal_count} proposals. "
            f"View at /console/artifacts/{artifact.get('id', '')}"
        )
        db.connection.execute(
            "INSERT INTO inbox_items"
            " (id, workspace_id, title, body, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, 'skill.memory_consolidation', ?, datetime('now'))",
            (nid, workspace_id, title, body, trace_id),
        )
        db.connection.commit()
    except Exception:
        pass
