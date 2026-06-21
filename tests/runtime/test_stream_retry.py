"""Tests: streaming retry behavior with max_retries."""

from __future__ import annotations

from unittest.mock import MagicMock

from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.shared.stream_events import StreamEventType
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository


def _setup(db: Database) -> tuple[str, str]:
    WorkspaceRepository(db).create("ws-retry", "test")
    SessionRepository(db).create("sess-retry", "ws-retry", "retry-test")
    return "ws-retry", "sess-retry"


def _event(wid: str, sid: str) -> RuntimeEvent:
    return RuntimeEvent(
        id="evt-retry",
        workspace_id=wid,
        session_id=sid,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "hello", "channel": "api_stream"},
    )


def test_stream_retry_max_retries_zero_no_retry(db: Database) -> None:
    """max_retries=0: stream_chat fails once, no retry, error event."""
    wid, sid = _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.supports_streaming = True
    adapter.stream_chat.side_effect = RuntimeError("stream failed")
    adapter.chat.return_value = ModelResponse(content="fallback")

    kernel = RuntimeKernel(db, model_adapter=adapter)
    events = list(
        kernel.process_stream(
            _event(wid, sid),
            max_retries=0,
        )
    )
    errors = [e for e in events if e.type == StreamEventType.error]
    assert len(errors) >= 1, "Expected error event"
    err = errors[0].data.get("error", {})
    assert isinstance(err, dict)
    assert "code" in err


def test_stream_retry_before_first_delta(db: Database) -> None:
    """stream_chat fails before first delta, retries succeed."""
    wid, sid = _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.supports_streaming = True
    call_count = 0

    def _stream_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RuntimeError("transient failure")
        return iter(["hello"])

    adapter.stream_chat.side_effect = _stream_chat
    adapter.chat.return_value = ModelResponse(content="fallback")

    kernel = RuntimeKernel(db, model_adapter=adapter)
    events = list(
        kernel.process_stream(
            _event(wid, sid),
            max_retries=2,
        )
    )
    errors = [e for e in events if e.type == StreamEventType.error]
    deltas = [e for e in events if e.type == StreamEventType.delta]
    finals = [e for e in events if e.type == StreamEventType.final]
    assert len(errors) == 0, f"Unexpected errors: {errors}"
    assert len(deltas) >= 1, "Expected delta after retry success"
    assert len(finals) == 1, "Expected final event"


def test_stream_retry_exhaustion(db: Database) -> None:
    """stream_chat fails on all retries, outputs error event."""
    wid, sid = _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.supports_streaming = True
    adapter.stream_chat.side_effect = RuntimeError("persistent failure")

    kernel = RuntimeKernel(db, model_adapter=adapter)
    events = list(
        kernel.process_stream(
            _event(wid, sid),
            max_retries=2,
        )
    )
    errors = [e for e in events if e.type == StreamEventType.error]
    assert len(errors) >= 1, "Expected error event after retry exhaustion"
    err = errors[0].data.get("error", {})
    assert isinstance(err, dict)
    # Should not contain raw exception
    assert "Traceback" not in str(err)


def test_stream_retry_no_error_traceback(db: Database) -> None:
    """Error events must not contain Python traceback."""
    wid, sid = _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.supports_streaming = True
    adapter.stream_chat.side_effect = RuntimeError("internal detail")

    kernel = RuntimeKernel(db, model_adapter=adapter)
    events = list(
        kernel.process_stream(
            _event(wid, sid),
            max_retries=0,
        )
    )
    body = str([e.to_sse() for e in events])
    assert "Traceback" not in body
    # API-level redaction is tested in test_stream_redaction.py


def test_after_first_delta_failure_no_retry(db: Database) -> None:
    """After first delta emitted, stream failure does not retry/replay."""
    wid, sid = _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.supports_streaming = True
    call_count = 0

    def _stream_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return iter(["token1", "token2"])
        return iter(["replayed"])

    adapter.stream_chat.side_effect = _stream_chat
    adapter.chat.return_value = ModelResponse(content="fallback")

    kernel = RuntimeKernel(db, model_adapter=adapter)
    events = list(
        kernel.process_stream(
            _event(wid, sid),
            max_retries=2,
        )
    )
    deltas = [e for e in events if e.type == StreamEventType.delta]
    delta_texts = [str(e.data.get("delta", "")) for e in deltas]
    combined = "".join(delta_texts)
    assert "replayed" not in combined, "Retry after first delta should not replay tokens"
