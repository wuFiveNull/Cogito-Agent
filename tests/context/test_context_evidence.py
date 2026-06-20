from __future__ import annotations

import json

from cogito_agent.context import ContextEngine
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


def test_context_items_include_quality_evidence_and_stable_refs() -> None:
    items = ContextEngine().build(
        recent_messages=[],
        memories=[
            {
                "id": "memory-1",
                "text": "Remembered fact",
                "confidence": 0.9,
                "freshness_score": 0.8,
                "lineage_info": {"source_message_id": "message-1"},
            }
        ],
        current_message="Question",
    )

    memory = next(item for item in items if item.source_type == "memory")
    assert memory.stable_ref == "memory:memory-1"
    assert memory.trust_score == 0.9
    assert memory.freshness_score == 0.8
    assert memory.evidence == [{"source_message_id": "message-1"}]


def test_context_exclusion_reason_is_separate_from_inclusion_reason() -> None:
    items = ContextEngine(total_token_budget=64).build(
        recent_messages=[{"id": "m1", "content": "x" * 1000}],
        memories=[],
        current_message="Question",
    )

    message = next(item for item in items if item.source_type == "message")
    assert message.included is False
    assert message.reason == "recent_history"
    assert message.exclusion_reason == "exceeded_recent_messages_budget"


def test_context_evidence_fields_are_persisted() -> None:
    db = Database()
    db.initialize()
    db.migrate()
    trace = Tracer(db).create_trace("workspace", "event")

    ContextEngine().build(
        recent_messages=[],
        memories=[
            {
                "id": "memory-1",
                "text": "Fact",
                "confidence": 0.7,
                "evidence": [{"artifact_id": "artifact-1"}],
            }
        ],
        current_message="Question",
        db=db,
        trace_id=trace.id,
        workspace_id="workspace",
    )

    row = db.connection.execute(
        "SELECT * FROM context_items WHERE stable_ref = 'memory:memory-1'"
    ).fetchone()
    assert row is not None
    assert row["trust_score"] == 0.7
    assert json.loads(row["evidence_json"]) == [{"artifact_id": "artifact-1"}]
    db.close()
