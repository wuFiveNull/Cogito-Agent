from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from .adapter import ModelAdapter, ModelResponse


class ProviderHealthStatus(StrEnum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    probing = "probing"


class ModelRouteRequest(BaseModel):
    required_capabilities: set[str] = Field(default_factory=set)
    estimated_input_tokens: int = 0
    max_output_tokens: int = 0
    min_quality_score: float = 0.0
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None
    preferred_provider: str = ""
    preferred_model: str = ""


class ModelCandidate(BaseModel):
    provider: str
    model: str
    capabilities: set[str] = Field(default_factory=set)
    context_window: int = 8192
    quality_score: float = 0.5
    expected_latency_ms: int = 1000
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    priority: int = 100
    enabled: bool = True

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    def estimated_cost(self, request: ModelRouteRequest) -> float:
        return (
            request.estimated_input_tokens * self.input_cost_per_million
            + request.max_output_tokens * self.output_cost_per_million
        ) / 1_000_000


class ModelExclusion(BaseModel):
    candidate_id: str
    reason_code: str
    detail: str


class ModelRouteDecision(BaseModel):
    selected: ModelCandidate | None = None
    fallback_order: list[ModelCandidate] = Field(default_factory=list)
    exclusions: list[ModelExclusion] = Field(default_factory=list)
    reason: str


class ModelRouteEventType(StrEnum):
    decision = "decision"
    attempt_failed = "attempt_failed"
    attempt_succeeded = "attempt_succeeded"


class ModelRouteEvent(BaseModel):
    """Provider-neutral telemetry emitted while executing a route decision."""

    type: ModelRouteEventType
    decision: ModelRouteDecision
    candidate: ModelCandidate | None = None
    attempt_index: int = 0
    remaining_candidates: int = 0
    error: str = ""


class ProviderHealth(BaseModel):
    provider: str
    status: ProviderHealthStatus = ProviderHealthStatus.healthy
    consecutive_failures: int = 0
    opened_until: float = 0.0
    last_error: str = ""


class ModelRouterProtocol(Protocol):
    def route(self, request: ModelRouteRequest) -> ModelRouteDecision: ...


class ModelRouter:
    """Deterministic local router with health cache and circuit breaking."""

    def __init__(
        self,
        candidates: Iterable[ModelCandidate] = (),
        *,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._candidates = {candidate.id: candidate for candidate in candidates}
        self._health: dict[str, ProviderHealth] = {}
        self._failure_threshold = max(1, failure_threshold)
        self._recovery_seconds = max(0.0, recovery_seconds)
        self._clock = clock

    def register(self, candidate: ModelCandidate) -> None:
        self._candidates[candidate.id] = candidate

    def unregister(self, candidate_id: str) -> None:
        self._candidates.pop(candidate_id, None)

    def get_health(self, provider: str) -> ProviderHealth:
        health = self._health.setdefault(provider, ProviderHealth(provider=provider))
        if (
            health.status == ProviderHealthStatus.unhealthy
            and self._clock() >= health.opened_until
        ):
            health.status = ProviderHealthStatus.probing
        return health.model_copy(deep=True)

    def report_success(self, provider: str) -> None:
        self._health[provider] = ProviderHealth(provider=provider)

    def report_failure(self, provider: str, error: str = "") -> ProviderHealth:
        health = self._health.setdefault(provider, ProviderHealth(provider=provider))
        health.consecutive_failures += 1
        health.last_error = error
        if health.consecutive_failures >= self._failure_threshold:
            health.status = ProviderHealthStatus.unhealthy
            health.opened_until = self._clock() + self._recovery_seconds
        else:
            health.status = ProviderHealthStatus.degraded
        return health.model_copy(deep=True)

    def route(self, request: ModelRouteRequest) -> ModelRouteDecision:
        eligible: list[tuple[ModelCandidate, ProviderHealth]] = []
        exclusions: list[ModelExclusion] = []
        for candidate in sorted(self._candidates.values(), key=lambda item: item.id):
            reason = self._exclusion_reason(candidate, request)
            if reason is not None:
                exclusions.append(
                    ModelExclusion(
                        candidate_id=candidate.id,
                        reason_code=reason[0],
                        detail=reason[1],
                    )
                )
                continue
            health = self.get_health(candidate.provider)
            if health.status == ProviderHealthStatus.unhealthy:
                exclusions.append(
                    ModelExclusion(
                        candidate_id=candidate.id,
                        reason_code="circuit_open",
                        detail="provider circuit breaker is open",
                    )
                )
                continue
            eligible.append((candidate, health))

        eligible.sort(key=lambda item: self._sort_key(item[0], item[1], request))
        ordered = [candidate for candidate, _health in eligible]
        if not ordered:
            return ModelRouteDecision(
                reason="no eligible model candidate",
                exclusions=exclusions,
            )
        return ModelRouteDecision(
            selected=ordered[0],
            fallback_order=ordered[1:],
            exclusions=exclusions,
            reason="selected by deterministic preference, health, quality, cost and latency",
        )

    def _exclusion_reason(
        self, candidate: ModelCandidate, request: ModelRouteRequest
    ) -> tuple[str, str] | None:
        if not candidate.enabled:
            return "disabled", "candidate is disabled"
        missing = request.required_capabilities - candidate.capabilities
        if missing:
            return "missing_capability", ", ".join(sorted(missing))
        required_context = request.estimated_input_tokens + request.max_output_tokens
        if required_context > candidate.context_window:
            detail = f"requires {required_context}, supports {candidate.context_window}"
            return "context_window", detail
        if candidate.quality_score < request.min_quality_score:
            return "quality", "quality score is below the requested minimum"
        if (
            request.max_latency_ms is not None
            and candidate.expected_latency_ms > request.max_latency_ms
        ):
            return "latency", "expected latency exceeds the requested maximum"
        estimated_cost = candidate.estimated_cost(request)
        if request.max_cost_usd is not None and estimated_cost > request.max_cost_usd:
            return "budget", f"estimated cost {estimated_cost:.6f} exceeds budget"
        return None

    @staticmethod
    def _sort_key(
        candidate: ModelCandidate,
        health: ProviderHealth,
        request: ModelRouteRequest,
    ) -> tuple[object, ...]:
        preferred_model = bool(
            request.preferred_model
            and candidate.model == request.preferred_model
            and (
                not request.preferred_provider
                or candidate.provider == request.preferred_provider
            )
        )
        preferred_provider = bool(
            request.preferred_provider
            and candidate.provider == request.preferred_provider
        )
        health_rank = {
            ProviderHealthStatus.healthy: 0,
            ProviderHealthStatus.probing: 1,
            ProviderHealthStatus.degraded: 2,
            ProviderHealthStatus.unhealthy: 3,
        }[health.status]
        return (
            not preferred_model,
            not preferred_provider,
            health_rank,
            candidate.priority,
            -candidate.quality_score,
            candidate.estimated_cost(request),
            candidate.expected_latency_ms,
            candidate.id,
        )


class RoutedModelAdapter:
    """ModelAdapter that executes a route decision with deterministic fallback."""

    supports_streaming = True

    def __init__(
        self,
        router: ModelRouterProtocol,
        resolver: Callable[[ModelCandidate], ModelAdapter],
        *,
        decision_observer: Callable[[ModelRouteDecision], None] | None = None,
        route_observer: Callable[[ModelRouteEvent], None] | None = None,
    ) -> None:
        self._router = router
        self._resolver = resolver
        self._decision_observer = decision_observer
        self._route_observer = route_observer
        self.provider = ""
        self.model = ""

    def chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> ModelResponse:
        request = self._request_for(messages, kwargs)
        decision = self._router.route(request)
        self._observe(decision)
        candidates = self._ordered_candidates(decision)
        if not candidates:
            raise RuntimeError("No eligible model candidate")
        errors: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            adapter = self._resolver(candidate)
            self.provider, self.model = candidate.provider, candidate.model
            forwarded = dict(kwargs)
            forwarded.pop("route_request", None)
            try:
                response = adapter.chat(messages, **forwarded)
                if response.error:
                    raise RuntimeError(response.error)
            except Exception as exc:
                errors.append(f"{candidate.id}: {exc}")
                self._report_failure(candidate.provider, str(exc))
                self._observe_route(
                    ModelRouteEvent(
                        type=ModelRouteEventType.attempt_failed,
                        decision=decision,
                        candidate=candidate,
                        attempt_index=index,
                        remaining_candidates=len(candidates) - index,
                        error=str(exc),
                    )
                )
                continue
            self._report_success(candidate.provider)
            response.provider = response.provider or candidate.provider
            response.model = response.model or candidate.model
            self._observe_route(
                ModelRouteEvent(
                    type=ModelRouteEventType.attempt_succeeded,
                    decision=decision,
                    candidate=candidate,
                    attempt_index=index,
                    remaining_candidates=len(candidates) - index,
                )
            )
            return response
        raise RuntimeError("All routed model candidates failed: " + "; ".join(errors))

    def stream_chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> Iterator[str]:
        request = self._request_for(messages, kwargs)
        decision = self._router.route(request)
        self._observe(decision)
        candidates = self._ordered_candidates(decision)
        if not candidates:
            raise RuntimeError("No eligible model candidate")
        errors: list[str] = []
        for index, candidate in enumerate(candidates, start=1):
            adapter = self._resolver(candidate)
            self.provider, self.model = candidate.provider, candidate.model
            forwarded = dict(kwargs)
            forwarded.pop("route_request", None)
            emitted = False
            try:
                if getattr(adapter, "supports_streaming", False):
                    for chunk in adapter.stream_chat(messages, **forwarded):
                        emitted = True
                        yield chunk
                else:
                    response = adapter.chat(messages, **forwarded)
                    if response.error:
                        raise RuntimeError(response.error)
                    if response.content:
                        emitted = True
                        yield response.content
            except Exception as exc:
                self._report_failure(candidate.provider, str(exc))
                if emitted:
                    self._observe_route(
                        ModelRouteEvent(
                            type=ModelRouteEventType.attempt_failed,
                            decision=decision,
                            candidate=candidate,
                            attempt_index=index,
                            remaining_candidates=0,
                            error=str(exc),
                        )
                    )
                    raise RuntimeError(
                        f"Streaming model {candidate.id} failed after emitting output"
                    ) from exc
                errors.append(f"{candidate.id}: {exc}")
                self._observe_route(
                    ModelRouteEvent(
                        type=ModelRouteEventType.attempt_failed,
                        decision=decision,
                        candidate=candidate,
                        attempt_index=index,
                        remaining_candidates=len(candidates) - index,
                        error=str(exc),
                    )
                )
                continue
            self._report_success(candidate.provider)
            self._observe_route(
                ModelRouteEvent(
                    type=ModelRouteEventType.attempt_succeeded,
                    decision=decision,
                    candidate=candidate,
                    attempt_index=index,
                    remaining_candidates=len(candidates) - index,
                )
            )
            return
        raise RuntimeError("All routed model candidates failed: " + "; ".join(errors))

    @staticmethod
    def _ordered_candidates(decision: ModelRouteDecision) -> list[ModelCandidate]:
        if decision.selected is None:
            return []
        return [decision.selected, *decision.fallback_order]

    @staticmethod
    def _request_for(
        messages: list[dict[str, object]], kwargs: dict[str, object]
    ) -> ModelRouteRequest:
        explicit = kwargs.get("route_request")
        if isinstance(explicit, ModelRouteRequest):
            return explicit
        text_size = sum(len(str(message.get("content", ""))) for message in messages)
        capabilities = {"chat"}
        if kwargs.get("tools"):
            capabilities.add("tools")
        max_output = kwargs.get("max_tokens", 4000)
        return ModelRouteRequest(
            required_capabilities=capabilities,
            estimated_input_tokens=max(1, text_size // 4),
            max_output_tokens=int(max_output) if isinstance(max_output, int) else 4000,
        )

    def _observe(self, decision: ModelRouteDecision) -> None:
        if self._decision_observer is not None:
            self._decision_observer(decision)
        self._observe_route(
            ModelRouteEvent(type=ModelRouteEventType.decision, decision=decision)
        )

    def set_route_observer(
        self, observer: Callable[[ModelRouteEvent], None] | None
    ) -> None:
        """Bind turn-scoped telemetry without coupling the router to storage."""
        self._route_observer = observer

    def _observe_route(self, event: ModelRouteEvent) -> None:
        if self._route_observer is not None:
            self._route_observer(event)

    def _report_success(self, provider: str) -> None:
        reporter = getattr(self._router, "report_success", None)
        if callable(reporter):
            reporter(provider)

    def _report_failure(self, provider: str, error: str) -> None:
        reporter = getattr(self._router, "report_failure", None)
        if callable(reporter):
            reporter(provider, error)
