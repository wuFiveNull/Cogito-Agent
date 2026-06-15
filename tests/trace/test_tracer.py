from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


def test_create_trace(tracer: Tracer) -> None:
    trace = tracer.create_trace("ws-1", "evt-1")
    assert trace.workspace_id == "ws-1"
    assert trace.root_event_id == "evt-1"
    assert trace.status == "running"


def test_create_span(tracer: Tracer) -> None:
    trace = tracer.create_trace("ws-1", "evt-1")
    span = tracer.create_span(trace.id, "test-span", SpanKind.runtime)
    assert span.trace_id == trace.id
    assert span.name == "test-span"
    assert span.kind == SpanKind.runtime


def test_create_trace_with_session(tracer: Tracer) -> None:
    trace = tracer.create_trace("ws-1", "evt-1", session_id="sess-1")
    assert trace.session_id == "sess-1"


def test_end_span(tracer: Tracer) -> None:
    trace = tracer.create_trace("ws-1", "evt-1")
    span = tracer.create_span(trace.id, "test", SpanKind.model)
    tracer.end_span(span)
    assert span.status == "completed"
    assert span.ended_at is not None


def test_end_trace(tracer: Tracer) -> None:
    trace = tracer.create_trace("ws-1", "evt-1")
    tracer.end_trace(trace, status="failed")
    assert trace.status == "failed"
    assert trace.ended_at is not None


def test_log_tool_call(tracer: Tracer, db: Database) -> None:
    trace = tracer.create_trace("ws-1", "evt-1")
    span = tracer.create_span(trace.id, "tool", SpanKind.tool)
    tracer.log_tool_call(
        trace_id=trace.id,
        span_id=span.id,
        capability_name="file.read",
        decision="allow",
        status="ok",
    )
    cur = db.connection.execute(
        "SELECT * FROM tool_calls WHERE trace_id = ?", (trace.id,)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["capability_name"] == "file.read"


def test_log_model_call(tracer: Tracer, db: Database) -> None:
    trace = tracer.create_trace("ws-1", "evt-1")
    span = tracer.create_span(trace.id, "model", SpanKind.model)
    tracer.log_model_call(
        trace_id=trace.id,
        span_id=span.id,
        provider="openai",
        model="gpt-4o-mini",
        input_token_count=100,
        output_token_count=50,
    )
    cur = db.connection.execute(
        "SELECT * FROM model_calls WHERE trace_id = ?", (trace.id,)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["provider"] == "openai"
