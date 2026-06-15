import pytest
from pydantic import ValidationError

from cogito_agent.shared import EventSource, EventType, RuntimeEvent


def test_valid_event() -> None:
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "hello"},
    )
    assert event.workspace_id == "ws-1"
    assert event.source == EventSource.cli
    assert event.type == EventType.user_message


def test_event_defaults() -> None:
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.api,
        type=EventType.tool_result,
        payload={"result": "ok"},
    )
    assert event.id is not None
    assert event.created_at is not None
    assert event.parent_trace_id is None


def test_invalid_event_missing_fields() -> None:
    with pytest.raises(ValidationError):
        RuntimeEvent()  # type: ignore[call-arg]


def test_event_source_values() -> None:
    assert EventSource.cli.value == "cli"
    assert EventSource.api.value == "api"


def test_event_type_values() -> None:
    assert EventType.user_message.value == "user_message"
    assert EventType.interrupt.value == "interrupt"
