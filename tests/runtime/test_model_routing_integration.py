from __future__ import annotations

from collections.abc import Iterator

from cogito_agent.models import (
    ModelCandidate,
    ModelResponse,
    ModelRouter,
    RoutedModelAdapter,
)
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, TurnState
from cogito_agent.storage import Database, SessionRepository, WorkspaceRepository


class _Adapter:
    supports_streaming = True

    def __init__(self, response: ModelResponse) -> None:
        self._response = response

    def chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> ModelResponse:
        del messages, kwargs
        return self._response

    def stream_chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> Iterator[str]:
        del messages, kwargs
        if self._response.error:
            raise RuntimeError(self._response.error)
        yield self._response.content


def _event() -> RuntimeEvent:
    return RuntimeEvent(
        workspace_id="ws-route",
        session_id="session-route",
        actor_id="route-user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "route this request"},
    )


def test_runtime_persists_route_decision_fallback_and_redacts_error(
    db: Database,
) -> None:
    WorkspaceRepository(db).create("ws-route", "routing")
    SessionRepository(db).create("session-route", "ws-route", "routing")
    primary = ModelCandidate(
        provider="primary",
        model="primary-model",
        capabilities={"chat"},
        priority=1,
    )
    fallback = ModelCandidate(
        provider="fallback",
        model="fallback-model",
        capabilities={"chat"},
        priority=2,
    )
    excluded = ModelCandidate(
        provider="disabled",
        model="disabled-model",
        capabilities={"chat"},
        enabled=False,
    )
    adapters = {
        primary.id: _Adapter(
            ModelResponse(error="Bearer sk-route-secret failed")
        ),
        fallback.id: _Adapter(ModelResponse(content="fallback answer")),
    }
    routed = RoutedModelAdapter(
        ModelRouter([primary, fallback, excluded]),
        lambda candidate: adapters[candidate.id],
    )

    result = RuntimeKernel(db, model_adapter=routed).process(_event())

    assert result.state == TurnState.completed
    assert result.output == "fallback answer"
    audits = db.connection.execute(
        "SELECT action, decision, details FROM audit_logs "
        "WHERE resource = 'model_router' ORDER BY created_at"
    ).fetchall()
    assert [row["action"] for row in audits] == [
        "model_route_decided",
        "model_route_attempt_failed",
        "model_route_selected",
    ]
    assert audits[1]["decision"] == "fallback"
    combined_details = " ".join(str(row["details"]) for row in audits)
    assert "disabled:disabled-model" in combined_details
    assert "sk-route-secret" not in combined_details
    route_spans = db.connection.execute(
        "SELECT name, status FROM spans "
        "WHERE trace_id = ? AND name LIKE 'model.route%'",
        (result.trace_id,),
    ).fetchall()
    assert [(row["name"], row["status"]) for row in route_spans] == [
        ("model.route", "completed"),
        ("model.route.attempt", "failed"),
        ("model.route.attempt", "completed"),
    ]
