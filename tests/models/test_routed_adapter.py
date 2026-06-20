from __future__ import annotations

from collections.abc import Iterator

import pytest

from cogito_agent.models import (
    ModelAdapter,
    ModelCandidate,
    ModelResponse,
    ModelRouteDecision,
    ModelRouteEvent,
    ModelRouteEventType,
    ModelRouter,
    RoutedModelAdapter,
)


class FakeAdapter:
    supports_streaming = True

    def __init__(self, *, content: str = "ok", error: Exception | None = None) -> None:
        self.content = content
        self.error = error

    def chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> ModelResponse:
        del messages, kwargs
        if self.error:
            raise self.error
        return ModelResponse(content=self.content)

    def stream_chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> Iterator[str]:
        del messages, kwargs
        if self.error:
            raise self.error
        yield self.content


def _candidate(provider: str, priority: int) -> ModelCandidate:
    return ModelCandidate(
        provider=provider,
        model="chat",
        capabilities={"chat", "tools"},
        priority=priority,
    )


def test_routed_adapter_falls_back_and_reports_health() -> None:
    primary = _candidate("primary", 1)
    fallback = _candidate("fallback", 2)
    router = ModelRouter([primary, fallback])
    adapters = {
        primary.id: FakeAdapter(error=TimeoutError("timeout")),
        fallback.id: FakeAdapter(content="fallback result"),
    }
    observed: list[ModelRouteDecision] = []
    route_events: list[ModelRouteEvent] = []
    def resolve(candidate: ModelCandidate) -> ModelAdapter:
        return adapters[candidate.id]

    adapter = RoutedModelAdapter(
        router,
        resolve,
        decision_observer=observed.append,
        route_observer=route_events.append,
    )

    response = adapter.chat([{"role": "user", "content": "hello"}])

    assert response.content == "fallback result"
    assert response.provider == "fallback"
    assert response.model == "chat"
    assert router.get_health("primary:chat").consecutive_failures == 1
    assert len(observed) == 1
    assert [event.type for event in route_events] == [
        ModelRouteEventType.decision,
        ModelRouteEventType.attempt_failed,
        ModelRouteEventType.attempt_succeeded,
    ]
    assert route_events[1].remaining_candidates == 1
    assert route_events[2].candidate == fallback


def test_routed_adapter_infers_tools_capability() -> None:
    incapable = ModelCandidate(
        provider="plain", model="m", capabilities={"chat"}, priority=1
    )
    capable = _candidate("tools", 2)
    router = ModelRouter([incapable, capable])
    def resolve(_candidate: ModelCandidate) -> ModelAdapter:
        return FakeAdapter()

    adapter = RoutedModelAdapter(router, resolve)

    response = adapter.chat(
        [{"role": "user", "content": "use a tool"}], tools=[{"type": "function"}]
    )

    assert response.provider == "tools"


def test_stream_falls_back_only_before_output() -> None:
    primary = _candidate("primary", 1)
    fallback = _candidate("fallback", 2)
    router = ModelRouter([primary, fallback])
    adapters = {
        primary.id: FakeAdapter(error=ConnectionError("offline")),
        fallback.id: FakeAdapter(content="streamed"),
    }
    def resolve(candidate: ModelCandidate) -> ModelAdapter:
        return adapters[candidate.id]

    adapter = RoutedModelAdapter(router, resolve)

    assert list(adapter.stream_chat([{"role": "user", "content": "hello"}])) == [
        "streamed"
    ]


def test_routed_adapter_raises_when_no_candidate_is_eligible() -> None:
    router = ModelRouter([])
    def resolve(_candidate: ModelCandidate) -> ModelAdapter:
        return FakeAdapter()

    adapter = RoutedModelAdapter(router, resolve)

    with pytest.raises(RuntimeError, match="No eligible"):
        adapter.chat([{"role": "user", "content": "hello"}])
