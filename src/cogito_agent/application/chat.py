from __future__ import annotations

from collections.abc import Generator
from typing import Protocol

from cogito_agent.runtime.kernel import TurnResult
from cogito_agent.shared import RuntimeEvent
from cogito_agent.shared.stream_events import StreamEvent


class ChatRuntimePort(Protocol):
    def process(self, event: RuntimeEvent) -> TurnResult: ...

    def process_stream(
        self,
        event: RuntimeEvent,
        *,
        request_id: str = "",
        streaming_enabled: bool = True,
        max_retries: int = 2,
    ) -> Generator[StreamEvent, None, None]: ...

    def resume(self, event: RuntimeEvent) -> TurnResult: ...

    def interrupt(self, event: RuntimeEvent) -> None: ...


class ChatApplicationService:
    """Channel-neutral application boundary for one chat turn."""

    def __init__(self, runtime: ChatRuntimePort) -> None:
        self._runtime = runtime

    def process(self, event: RuntimeEvent) -> TurnResult:
        return self._runtime.process(event)

    def process_stream(
        self,
        event: RuntimeEvent,
        *,
        request_id: str = "",
        streaming_enabled: bool = True,
        max_retries: int = 2,
    ) -> Generator[StreamEvent, None, None]:
        yield from self._runtime.process_stream(
            event,
            request_id=request_id,
            streaming_enabled=streaming_enabled,
            max_retries=max_retries,
        )

    def resume(self, event: RuntimeEvent) -> TurnResult:
        return self._runtime.resume(event)

    def interrupt(self, event: RuntimeEvent) -> None:
        self._runtime.interrupt(event)
