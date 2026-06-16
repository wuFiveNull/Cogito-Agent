from __future__ import annotations

from cogito_agent.cli.replay import TraceInspector
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


def _seed_test_data(db: Database) -> str:
    repo = WorkspaceRepository(db)
    ws = repo.create("ws_obs", "ObservabilityTest")
    ws_id = str(ws["id"])
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
        " VALUES ('tr_obs_1', ?, 'evt_1', 'completed', '2025-01-01T00:00:00')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
        " VALUES ('tr_obs_2', ?, 'evt_2', 'failed', '2025-06-01T00:00:00')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO spans (id, trace_id, name, kind, status)"
        " VALUES ('sp_obs', 'tr_obs_1', 'test', 'runtime', 'ok')",
    )
    db.connection.execute(
        "INSERT INTO model_calls (trace_id, span_id, provider, model, prompt_summary, response_summary)"
        " VALUES ('tr_obs_1', 'sp_obs', 'mock', 'mock-chat', 'test prompt', 'test response')",
    )
    db.connection.execute(
        "INSERT INTO tool_calls (trace_id, span_id, capability_name, decision, input_summary, output_summary)"
        " VALUES ('tr_obs_1', 'sp_obs', 'time.now', 'allow', '{}', 'current time')",
    )
    db.connection.execute(
        "INSERT INTO audit_logs (id, workspace_id, actor_id, action, resource, decision)"
        " VALUES ('aud_obs_1', ?, 'user', 'test', 'resource', 'allow')",
        (ws_id,),
    )
    db.connection.execute(
        "INSERT INTO audit_logs (id, workspace_id, actor_id, action, resource, decision)"
        " VALUES ('aud_obs_2', ?, 'system', 'maintenance', 'database', 'allow')",
        (ws_id,),
    )
    db.connection.commit()
    return ws_id


def test_traces_list_empty() -> None:
    db = Database()
    db.initialize()
    inspector = TraceInspector(db)
    traces = inspector.list_traces(workspace_id="*")
    assert isinstance(traces, list)


def test_traces_list_with_data() -> None:
    db = Database()
    db.initialize()
    _seed_test_data(db)
    inspector = TraceInspector(db)
    traces = inspector.list_traces(workspace_id="*")
    assert len(traces) >= 2


def test_traces_show_detail() -> None:
    db = Database()
    db.initialize()
    _seed_test_data(db)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full("tr_obs_1")
    assert trace is not None
    assert "spans" in trace
    assert "model_calls" in trace
    assert "tool_calls" in trace
    assert len(trace["model_calls"]) >= 1
    assert len(trace["tool_calls"]) >= 1


def test_traces_show_not_found() -> None:
    db = Database()
    db.initialize()
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full("nonexistent")
    assert trace is None


def test_traces_format_detail() -> None:
    db = Database()
    db.initialize()
    _seed_test_data(db)
    inspector = TraceInspector(db)
    detail = inspector.format_trace_detail(inspector.get_trace_full("tr_obs_1"))
    assert "Trace:" in detail
    assert "Model Calls" in detail
    assert "Tool Calls" in detail


def test_audit_list_empty() -> None:
    db = Database()
    db.initialize()
    cur = db.connection.execute(
        "SELECT COUNT(*) as cnt FROM audit_logs"
    )
    assert cur.fetchone()["cnt"] == 0


def test_audit_list_with_data() -> None:
    db = Database()
    db.initialize()
    _seed_test_data(db)
    cur = db.connection.execute("SELECT COUNT(*) as cnt FROM audit_logs")
    assert cur.fetchone()["cnt"] >= 2


def test_audit_show_detail() -> None:
    db = Database()
    db.initialize()
    _seed_test_data(db)
    cur = db.connection.execute(
        "SELECT * FROM audit_logs WHERE id = 'aud_obs_1'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["actor_id"] == "user"
    assert row["action"] == "test"


def test_usage_summary_counts() -> None:
    db = Database()
    db.initialize()
    _seed_test_data(db)
    cur = db.connection.execute("SELECT COUNT(*) as cnt FROM traces")
    assert cur.fetchone()["cnt"] >= 2
    cur = db.connection.execute(
        "SELECT COUNT(*) as cnt FROM model_calls mc"
        " JOIN traces t ON mc.trace_id = t.id"
    )
    assert cur.fetchone()["cnt"] >= 1
    cur = db.connection.execute(
        "SELECT COUNT(*) as cnt FROM tool_calls tc"
        " JOIN traces t ON tc.trace_id = t.id"
    )
    assert cur.fetchone()["cnt"] >= 1
    cur = db.connection.execute("SELECT COUNT(*) as cnt FROM audit_logs")
    assert cur.fetchone()["cnt"] >= 2
