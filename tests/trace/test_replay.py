from __future__ import annotations

import uuid
from typing import cast

from cogito_agent.cli.replay import TraceInspector
from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


def _seed_trace(db: Database, tracer: Tracer) -> str:
    trace = tracer.create_trace("ws-1", "evt-1", session_id="sess-1")
    span = tracer.create_span(trace.id, "context-build", SpanKind.context)
    tracer.end_span(span)
    tracer.log_model_call(
        trace_id=trace.id, span_id=span.id,
        provider="openai", model="gpt-4o-mini",
        input_token_count=100, output_token_count=50,
        prompt_summary="Hello", response_summary="Hi there",
        latency_ms=200,
    )
    tracer.log_tool_call(
        trace_id=trace.id, span_id=span.id,
        capability_name="file.read",
        input_summary="read /tmp/test.txt",
        decision="allow", status="ok",
        output_summary="file content", latency_ms=50,
    )
    # Audit log entry
    db.connection.execute(
        "INSERT INTO audit_logs"
        " (actor_id, action, resource, workspace_id, session_id, trace_id, decision, reason)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("user", "call_tool", "file.read", "ws-1",
         "sess-1", trace.id, "allow", "allowed by policy"),
    )
    db.connection.commit()
    # Source lineage entry
    db.connection.execute(
        "INSERT INTO source_lineage"
        " (id, trace_id, output_ref, source_type, source_id, span_id, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), trace.id, "output-1", "memory", "mem-1", span.id, "from FTS5"),
    )
    db.connection.commit()
    tracer.end_trace(trace, status="completed")
    return str(trace.id)


def test_list_traces(db: Database, tracer: Tracer) -> None:
    tid = _seed_trace(db, tracer)
    inspector = TraceInspector(db)
    traces = inspector.list_traces("ws-1")
    assert len(traces) >= 1
    ids = [t["id"] for t in traces]
    assert tid in ids


def test_list_traces_empty(db: Database) -> None:
    inspector = TraceInspector(db)
    traces = inspector.list_traces("ws-1")
    assert traces == []


def test_get_trace_full_not_found(db: Database) -> None:
    inspector = TraceInspector(db)
    result = inspector.get_trace_full("nonexistent")
    assert result is None


def test_get_trace_full_with_all_data(db: Database, tracer: Tracer) -> None:
    tid = _seed_trace(db, tracer)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(tid)
    assert trace is not None
    assert trace["status"] == "completed"
    assert trace["session_id"] == "sess-1"
    spans = cast("list[object]", trace["spans"])
    assert len(spans) == 1
    model_calls = cast("list[object]", trace["model_calls"])
    assert len(model_calls) == 1
    tool_calls = cast("list[object]", trace["tool_calls"])
    assert len(tool_calls) == 1
    audit_logs = cast("list[object]", trace["audit_logs"])
    assert len(audit_logs) == 1
    lineage = cast("list[object]", trace["source_lineage"])
    assert len(lineage) == 1
    state_path = cast("list[object]", trace["state_path"])
    assert len(state_path) == 1


def test_format_trace_card(db: Database, tracer: Tracer) -> None:
    tid = _seed_trace(db, tracer)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(tid)
    assert trace is not None
    card = inspector.format_trace_card(trace)
    assert "Trace:" in card
    assert "Status: completed" in card
    assert "Model calls: 1" in card
    assert "Tool calls: 1" in card


def test_format_trace_detail(db: Database, tracer: Tracer) -> None:
    tid = _seed_trace(db, tracer)
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(tid)
    assert trace is not None
    detail = inspector.format_trace_detail(trace)
    assert "Trace:" in detail
    assert "Model Calls (1)" in detail
    assert "Tool Calls (1)" in detail
    assert "Policy Decisions (1)" in detail
    assert "Source Lineage (1)" in detail


def test_get_trace_full_redaction(db: Database, tracer: Tracer) -> None:
    trace_obj = tracer.create_trace("ws-1", "evt-2", session_id="sess-1")
    tid = str(trace_obj.id)
    span = tracer.create_span(tid, "tool-span", SpanKind.tool)
    tracer.log_tool_call(
        trace_id=tid, span_id=span.id,
        capability_name="secret.read",
        input_summary="api_key=sk-abcdef1234567890abcdef12",
        decision="allow", status="ok",
        output_summary="Bearer my-secret-token",
    )
    tracer.end_span(span)
    tracer.end_trace(trace_obj, status="completed")

    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(tid)
    assert trace is not None
    tcs = cast("list[dict[str, object]]", trace["tool_calls"])
    assert len(tcs) == 1
    inp = str(tcs[0].get("input_summary", ""))
    outp = str(tcs[0].get("output_summary", ""))
    assert "sk-abcdef1234567890abcdef12" not in inp
    assert "[REDACTED]" in inp
    assert "my-secret-token" not in outp
    assert "[REDACTED]" in outp
