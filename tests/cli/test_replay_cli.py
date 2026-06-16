from __future__ import annotations

from cogito_agent.cli.replay import TraceInspector
from cogito_agent.storage import Database


def _seed_trace(db: Database) -> str:
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
        " VALUES ('tr_test1', 'ws_test', 'evt_1', 'completed', '2025-01-01T00:00:00')"
    )
    db.connection.execute(
        "INSERT INTO spans (id, trace_id, name, kind, status, started_at)"
        " VALUES ('sp_1', 'tr_test1', 'process_turn', 'runtime', 'completed',"
        " '2025-01-01T00:00:00')"
    )
    db.connection.execute(
        "INSERT INTO model_calls"
        " (trace_id, span_id, provider, model, input_token_count, output_token_count,"
        " latency_ms, prompt_summary, response_summary, stop_reason)"
        " VALUES ('tr_test1', 'sp_1', 'mock', 'mock-chat', 10, 20,"
        " 100, 'test prompt', 'test response', 'stop')"
    )
    db.connection.execute(
        "INSERT INTO tool_calls"
        " (trace_id, span_id, capability_name, decision, status, latency_ms,"
        " input_summary, output_summary)"
        " VALUES ('tr_test1', 'sp_1', 'time.now', 'allow', 'ok', 50,"
        " '{}', 'current time is ...')"
    )
    db.connection.execute(
        "INSERT INTO audit_logs"
        " (actor_id, action, resource, workspace_id, trace_id, decision, reason)"
        " VALUES ('user', 'call_tool', 'time.now', 'ws_test', 'tr_test1', 'allow', 'ok')"
    )
    db.connection.execute(
        "INSERT INTO source_lineage"
        " (trace_id, output_ref, source_type, source_id)"
        " VALUES ('tr_test1', 'output:text', 'memory', 'mem_1')"
    )
    db.connection.execute(
        "INSERT INTO context_items"
        " (trace_id, workspace_id, source_type, source_id, rank, token_estimate, included)"
        " VALUES ('tr_test1', 'ws_test', 'memory', 'mem_1', 1, 50, 1)"
    )
    db.connection.commit()
    return "tr_test1"


def test_replay_list_empty() -> None:
    db = Database()
    db.initialize()
    inspector = TraceInspector(db)
    traces = inspector.list_traces(workspace_id="*")
    assert isinstance(traces, list)


def test_replay_list_with_data() -> None:
    db = Database()
    db.initialize()
    trace_id = _seed_trace(db)
    inspector = TraceInspector(db)
    traces = inspector.list_traces(workspace_id="*")
    assert any(str(t.get("id", "")).startswith("tr_test") for t in traces)


def test_replay_show_with_tool_call() -> None:
    db = Database()
    db.initialize()
    trace_id = _seed_trace(db)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(trace_id)
    assert trace is not None
    assert trace["status"] == "completed"
    assert len(trace["spans"]) == 1
    assert len(trace["model_calls"]) == 1
    assert len(trace["tool_calls"]) == 1
    assert len(trace["audit_logs"]) == 1
    assert len(trace["source_lineage"]) == 1
    assert len(trace["context_items"]) == 1
    # verify redaction
    mc = trace["model_calls"][0]
    assert isinstance(mc.get("prompt_summary"), str)


def test_replay_show_not_found() -> None:
    db = Database()
    db.initialize()
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full("nonexistent")
    assert trace is None


def test_replay_format_card() -> None:
    db = Database()
    db.initialize()
    trace_id = _seed_trace(db)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(trace_id)
    assert trace is not None
    card = inspector.format_trace_card(trace)
    assert "Trace:" in card
    assert "Status:" in card


def test_replay_format_detail() -> None:
    db = Database()
    db.initialize()
    trace_id = _seed_trace(db)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(trace_id)
    assert trace is not None
    detail = inspector.format_trace_detail(trace)
    assert "Trace:" in detail
    assert "State Path" in detail
    assert "Model Calls" in detail
    assert "Tool Calls" in detail
    assert "Policy Decisions" in detail
    assert "Source Lineage" in detail
