from cogito_agent.shared import Span, SpanKind, Trace


def test_trace_defaults() -> None:
    t = Trace(workspace_id="ws-1", root_event_id="evt-1")
    assert t.status == "running"
    assert t.spans == []


def test_span_defaults() -> None:
    span = Span(trace_id="t-1", name="test", kind=SpanKind.runtime)
    assert span.status == "running"
    assert span.parent_span_id is None
