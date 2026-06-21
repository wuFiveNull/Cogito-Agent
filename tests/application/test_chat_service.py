from __future__ import annotations

from collections.abc import Generator

from cogito_agent.application import ChatApplicationService
from cogito_agent.runtime import TurnResult
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, TurnState
from cogito_agent.shared.stream_events import StreamEvent, StreamEventType


class FakeRuntime:
    def __init__(self) -> None:
        self.processed: list[str] = []

    def process(self, event: RuntimeEvent) -> TurnResult:
        self.processed.append(event.id)
        return TurnResult(TurnState.completed, output="ok")

    def process_stream(
        self,
        event: RuntimeEvent,
        *,
        request_id: str = "",
        streaming_enabled: bool = True,
        max_retries: int = 2,
    ) -> Generator[StreamEvent, None, None]:
        del event, streaming_enabled, max_retries
        yield StreamEvent(type=StreamEventType.final, data={"output": "ok"}, request_id=request_id)

    def resume(self, event: RuntimeEvent) -> TurnResult:
        return self.process(event)

    def interrupt(self, event: RuntimeEvent) -> None:
        self.processed.append(f"interrupt:{event.id}")


def _event() -> RuntimeEvent:
    return RuntimeEvent(
        workspace_id="workspace",
        session_id="session",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "hello"},
    )


def test_chat_service_delegates_channel_neutral_turn() -> None:
    runtime = FakeRuntime()
    service = ChatApplicationService(runtime)
    event = _event()
    result = service.process(event)
    assert result.output == "ok"
    assert runtime.processed == [event.id]


def test_chat_service_delegates_stream() -> None:
    service = ChatApplicationService(FakeRuntime())
    events = list(service.process_stream(_event(), request_id="request"))
    assert events[0].type == StreamEventType.final
    assert events[0].request_id == "request"
