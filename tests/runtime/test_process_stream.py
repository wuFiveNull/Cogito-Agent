"""Tests: RuntimeKernel.process_stream() yields proper StreamEvent sequence."""

from __future__ import annotations

from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.shared.stream_events import StreamEventType
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository
from tests.models.mock_model import MockModel


def _setup(db: Database) -> tuple[str, str]:
    ws = WorkspaceRepository(db)
    ws.create("ws-proc", "test")
    sess = SessionRepository(db)
    sess.create("sess-proc", "ws-proc", "test-proc")
    return "ws-proc", "sess-proc"


def _event(wid: str, session_id: str) -> RuntimeEvent:
    return RuntimeEvent(
        id="evt-proc",
        workspace_id=wid,
        session_id=session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "hello from process_stream test", "channel": "api_stream"},
    )


def test_process_stream_metadata_event(db: Database) -> None:
    wid, sid = _setup(db)
    kernel = RuntimeKernel(db, model_adapter=MockModel())
    events = list(kernel.process_stream(_event(wid, sid), request_id="req-123"))
    metadata = [e for e in events if e.type == StreamEventType.metadata]
    assert len(metadata) == 1, "Should have exactly one metadata event"
    m = metadata[0].data
    assert "trace_id" in m
    assert "request_id" in m
    assert m["request_id"] == "req-123"
    assert "channel" in m
    assert m["channel"] == "api_stream"
    assert "workspace_id" in m
    assert m["workspace_id"] == "ws-proc"


def test_process_stream_multiple_deltas(db: Database) -> None:
    wid, sid = _setup(db)
    adapter = MockModel(response_text="Hello world from mock model")
    kernel = RuntimeKernel(db, model_adapter=adapter)
    events = list(kernel.process_stream(_event(wid, sid)))
    deltas = [e for e in events if e.type == StreamEventType.delta]
    assert len(deltas) >= 2, f"Expected >=2 delta events, got {len(deltas)}"


def test_process_stream_final_event(db: Database) -> None:
    wid, sid = _setup(db)
    kernel = RuntimeKernel(db, model_adapter=MockModel())
    events = list(kernel.process_stream(_event(wid, sid)))
    finals = [e for e in events if e.type == StreamEventType.final]
    assert len(finals) == 1
    f = finals[0].data
    assert "response" in f
    assert "trace_id" in f
    assert "state" in f
    assert f["state"] == "completed"


def test_process_stream_event_order(db: Database) -> None:
    wid, sid = _setup(db)
    kernel = RuntimeKernel(db, model_adapter=MockModel())
    events = list(kernel.process_stream(_event(wid, sid)))
    types = [e.type for e in events]
    assert types[0] == StreamEventType.metadata
    assert types[-1] == StreamEventType.final
    assert StreamEventType.delta in types


def test_process_stream_no_model_adapter(db: Database) -> None:
    wid, sid = _setup(db)
    kernel = RuntimeKernel(db, model_adapter=None)
    events = list(kernel.process_stream(_event(wid, sid)))
    deltas = [e for e in events if e.type == StreamEventType.delta]
    finals = [e for e in events if e.type == StreamEventType.final]
    assert len(deltas) == 1, "Echo mode should produce exactly 1 delta"
    assert len(finals) == 1
    assert "You said:" in str(deltas[0].data.get("delta", ""))


def test_process_stream_empty_message(db: Database) -> None:
    wid, sid = _setup(db)
    kernel = RuntimeKernel(db, model_adapter=MockModel())
    evt = RuntimeEvent(
        id="evt-empty",
        workspace_id=wid,
        session_id=sid,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "", "channel": "api_stream"},
    )
    events = list(kernel.process_stream(evt))
    deltas = [e for e in events if e.type == StreamEventType.delta]
    finals = [e for e in events if e.type == StreamEventType.final]
    assert len(deltas) >= 1
    assert len(finals) == 1


def test_process_stream_model_error(db: Database) -> None:
    wid, sid = _setup(db)
    from cogito_agent.storage.repositories import SessionRepository

    SessionRepository(db).create("sess-err", wid, "error-test")
    adapter = MockModel(response_text="", fail_on_prompt="error")
    kernel = RuntimeKernel(db, model_adapter=adapter)
    evt = RuntimeEvent(
        id="evt-err",
        workspace_id=wid,
        session_id="sess-err",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "trigger error", "channel": "api_stream"},
    )
    events = list(kernel.process_stream(evt))
    errors = [e for e in events if e.type == StreamEventType.error]
    assert len(errors) >= 1
    err = errors[0].data.get("error", {})
    assert isinstance(err, dict)
    assert "code" in err
    assert "message" in err


def test_process_stream_trace_id_consistency(db: Database) -> None:
    wid, sid = _setup(db)
    kernel = RuntimeKernel(db, model_adapter=MockModel())
    events = list(kernel.process_stream(_event(wid, sid)))
    trace_ids = {str(e.trace_id) for e in events if e.trace_id}
    assert len(trace_ids) == 1, "All events should share the same trace_id"
    metadata = [e for e in events if e.type == StreamEventType.metadata]
    if metadata:
        assert metadata[0].data.get("trace_id") in trace_ids
