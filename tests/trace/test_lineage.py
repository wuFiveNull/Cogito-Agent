from cogito_agent.storage import Database
from cogito_agent.trace.lineage import SourceLineage


def test_record_lineage(db: Database) -> None:
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id) VALUES (?, ?, ?)",
        ("t1", "ws-1", "e1"),
    )
    db.connection.commit()
    lineage = SourceLineage(db)
    result = lineage.record(
        trace_id="t1",
        output_ref="response_1",
        source_type="memory",
        source_id="mem-1",
        span_id="s1",
        note="used for context",
    )
    assert result["source_type"] == "memory"
    assert result["output_ref"] == "response_1"


def test_list_by_trace(db: Database) -> None:
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id) VALUES (?, ?, ?)",
        ("t2", "ws-1", "e2"),
    )
    db.connection.commit()
    lineage = SourceLineage(db)
    lineage.record(trace_id="t2", output_ref="o1", source_type="memory", source_id="m1")
    lineage.record(trace_id="t2", output_ref="o2", source_type="tool", source_id="t1")
    results = lineage.list_by_trace("t2")
    assert len(results) == 2
