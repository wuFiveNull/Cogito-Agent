from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from .adapter import ModelAdapter, ModelResponse


def _default_capabilities() -> set[str]:
    return {"chat"}


def _default_roles() -> frozenset[str]:
    return frozenset({"chat"})


def _default_modalities() -> set[str]:
    return {"text"}


def _default_frozen_modalities() -> frozenset[str]:
    return frozenset({"text"})


def _default_frozen_output_formats() -> frozenset[str]:
    return frozenset()


# ── Error codes ───────────────────────────────────────────────────────────


class ModelRouteErrorCode(StrEnum):
    NO_MODEL_CANDIDATE = "NO_MODEL_CANDIDATE"
    NO_VISION_MODEL_AVAILABLE = "NO_VISION_MODEL_AVAILABLE"
    UNSUPPORTED_MODALITY = "UNSUPPORTED_MODALITY"
    NO_STRUCTURED_OUTPUT_MODEL = "NO_STRUCTURED_OUTPUT_MODEL"


# ── Health status ─────────────────────────────────────────────────────────


class ProviderHealthStatus(StrEnum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    probing = "probing"


# ── Roles ─────────────────────────────────────────────────────────────────


class ModelRole(StrEnum):
    router = "router"
    vision_worker = "vision_worker"
    planner = "planner"
    executor = "executor"
    coder = "coder"
    summarizer = "summarizer"
    reviewer = "reviewer"
    chat = "chat"


COMMON_CAPABILITIES: set[str] = {
    "chat",
    "vision",
    "ocr",
    "tools",
    "json",
    "reasoning",
    "code",
    "long_context",
    "streaming",
}

COMMON_MODALITIES: set[str] = {"text", "image", "file"}

COMMON_OUTPUT_FORMATS: set[str] = {"text", "json"}


# ── Route request ─────────────────────────────────────────────────────────


class ModelRouteRequest(BaseModel):
    required_capabilities: set[str] = Field(default_factory=_default_capabilities)
    required_input_modalities: set[str] = Field(default_factory=_default_modalities)
    required_output_formats: set[str] = Field(default_factory=set)
    role: str = ""
    task_kind: str = ""
    estimated_input_tokens: int = 0
    max_output_tokens: int = 0
    min_quality_score: float = 0.0
    max_latency_ms: int | None = None
    max_cost_usd: float | None = None
    preferred_provider: str = ""
    preferred_model: str = ""
    preferred_candidates: tuple[str, ...] = Field(default_factory=tuple)
    strict_preferred_candidates: bool = False
    chat_fallback_role: bool = True


# ── Candidate model ───────────────────────────────────────────────────────


class ModelCandidate(BaseModel):
    candidate_id: str = ""
    provider: str
    model: str
    capabilities: set[str] = Field(default_factory=_default_capabilities)
    roles: frozenset[str] = Field(default_factory=_default_roles)
    input_modalities: frozenset[str] = Field(default_factory=_default_frozen_modalities)
    output_formats: frozenset[str] = Field(default_factory=_default_frozen_output_formats)
    context_window: int = 8192
    quality_score: float = 0.5
    expected_latency_ms: int = 1000
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    priority: int = 100
    enabled: bool = True

    @field_validator("candidate_id", mode="before")
    @classmethod
    def _default_candidate_id(cls, v: str, info: object) -> str:
        return v

    @property
    def id(self) -> str:
        if self.candidate_id:
            return self.candidate_id
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
    error_code: ModelRouteErrorCode | None = None


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
    candidate_id: str
    status: ProviderHealthStatus = ProviderHealthStatus.healthy
    consecutive_failures: int = 0
    opened_until: float = 0.0
    last_error: str = ""


class ModelRouterProtocol(Protocol):
    def route(self, request: ModelRouteRequest) -> ModelRouteDecision: ...


class ModelRouter:
    """Deterministic local router with health cache and circuit breaking.

    Health tracking is at candidate_id granularity.
    """

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

    def get_health(self, candidate_id: str) -> ProviderHealth:
        health = self._health.setdefault(candidate_id, ProviderHealth(candidate_id=candidate_id))
        if health.status == ProviderHealthStatus.unhealthy and self._clock() >= health.opened_until:
            health.status = ProviderHealthStatus.probing
        return health.model_copy(deep=True)

    def report_success(self, candidate_id: str) -> None:
        self._health[candidate_id] = ProviderHealth(candidate_id=candidate_id)

    def report_failure(self, candidate_id: str, error: str = "") -> ProviderHealth:
        health = self._health.setdefault(candidate_id, ProviderHealth(candidate_id=candidate_id))
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
            health = self.get_health(candidate.id)
            if health.status == ProviderHealthStatus.unhealthy:
                exclusions.append(
                    ModelExclusion(
                        candidate_id=candidate.id,
                        reason_code="circuit_open",
                        detail="circuit breaker is open for this candidate",
                    )
                )
                continue
            eligible.append((candidate, health))

        eligible.sort(key=lambda item: self._sort_key(item[0], item[1], request))
        ordered = [candidate for candidate, _health in eligible]

        error_code: ModelRouteErrorCode | None = None
        if not ordered:
            has_vision_req = (
                "vision" in request.required_capabilities
                or "image" in request.required_input_modalities
            )
            has_output_fmt = bool(request.required_output_formats)
            if has_vision_req:
                error_code = ModelRouteErrorCode.NO_VISION_MODEL_AVAILABLE
            elif has_output_fmt and "json" in request.required_output_formats:
                error_code = ModelRouteErrorCode.NO_STRUCTURED_OUTPUT_MODEL
            else:
                error_code = ModelRouteErrorCode.NO_MODEL_CANDIDATE

        if not ordered:
            return ModelRouteDecision(
                reason="no eligible model candidate",
                exclusions=exclusions,
                error_code=error_code,
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

        missing_modalities = request.required_input_modalities - candidate.input_modalities
        if missing_modalities:
            return "missing_input_modality", ", ".join(sorted(missing_modalities))

        missing_formats = request.required_output_formats - candidate.output_formats
        if missing_formats:
            return "missing_output_format", ", ".join(sorted(missing_formats))

        if request.role and request.role not in candidate.roles:
            if request.chat_fallback_role and candidate.roles == frozenset({"chat"}):
                pass
            else:
                return "role_mismatch", f"required role '{request.role}' not in candidate roles"

        if request.strict_preferred_candidates and request.preferred_candidates:
            if candidate.id not in request.preferred_candidates:
                return "not_preferred", "candidate not in strict preferred_candidates list"

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
            and (not request.preferred_provider or candidate.provider == request.preferred_provider)
        )
        preferred_provider = bool(
            request.preferred_provider and candidate.provider == request.preferred_provider
        )

        preferred_candidate_idx: int = 9999
        if request.preferred_candidates:
            try:
                preferred_candidate_idx = request.preferred_candidates.index(candidate.id)
            except ValueError:
                pass

        health_rank = {
            ProviderHealthStatus.healthy: 0,
            ProviderHealthStatus.probing: 1,
            ProviderHealthStatus.degraded: 2,
            ProviderHealthStatus.unhealthy: 3,
        }[health.status]

        extra_modalities = len(candidate.input_modalities - request.required_input_modalities)
        extra_capabilities = len(candidate.capabilities - request.required_capabilities)

        return (
            not preferred_model,
            not preferred_provider,
            preferred_candidate_idx,
            extra_modalities,
            extra_capabilities,
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

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> ModelResponse:
        request = self._request_for(messages, kwargs)
        decision = self._router.route(request)
        self._observe(decision)
        candidates = self._ordered_candidates(decision)
        if not candidates:
            error_code = decision.error_code.value if decision.error_code else "NO_MODEL_CANDIDATE"
            raise RuntimeError(f"No eligible model candidate [{error_code}]")
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
                self._report_failure(candidate.id, str(exc))
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
            self._report_success(candidate.id)
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

    def stream_chat(self, messages: list[dict[str, object]], **kwargs: object) -> Iterator[str]:
        request = self._request_for(messages, kwargs)
        decision = self._router.route(request)
        self._observe(decision)
        candidates = self._ordered_candidates(decision)
        if not candidates:
            error_code = decision.error_code.value if decision.error_code else "NO_MODEL_CANDIDATE"
            raise RuntimeError(f"No eligible model candidate [{error_code}]")
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
                self._report_failure(candidate.id, str(exc))
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
            self._report_success(candidate.id)
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
        text_size = 0
        capabilities: set[str] = {"chat"}
        modalities: set[str] = {"text"}
        output_formats: set[str] = set()
        role = kwargs.pop("_route_role", "")
        task_kind = kwargs.pop("_route_task_kind", "")

        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                text_size += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        ptype = part.get("type", "text")
                        if ptype == "image":
                            modalities.add("image")
                            capabilities.add("vision")
                        elif ptype == "file":
                            modalities.add("file")
                        elif ptype == "text":
                            text_size += len(str(part.get("text", "")))
        if kwargs.get("tools"):
            capabilities.add("tools")
        max_output = kwargs.get("max_tokens", 4000)

        explicit_role = kwargs.pop("_route_role", role) or role
        explicit_task = kwargs.pop("_route_task_kind", task_kind) or task_kind

        pref_candidates_raw = kwargs.pop("_route_preferred_candidates", ())
        pref_candidates: tuple[str, ...] = (
            tuple(pref_candidates_raw) if isinstance(pref_candidates_raw, (list, tuple)) else ()
        )

        strict_preferred = bool(kwargs.pop("_route_strict_preferred", False))

        return ModelRouteRequest(
            required_capabilities=capabilities,
            required_input_modalities=modalities,
            required_output_formats=output_formats,
            role=str(explicit_role),
            task_kind=str(explicit_task),
            estimated_input_tokens=max(1, text_size // 4),
            max_output_tokens=int(max_output) if isinstance(max_output, (int, float)) else 4000,
            preferred_candidates=pref_candidates,
            strict_preferred_candidates=strict_preferred,
        )

    def _observe(self, decision: ModelRouteDecision) -> None:
        if self._decision_observer is not None:
            self._decision_observer(decision)
        self._observe_route(ModelRouteEvent(type=ModelRouteEventType.decision, decision=decision))

    def set_route_observer(self, observer: Callable[[ModelRouteEvent], None] | None) -> None:
        """Bind turn-scoped telemetry without coupling the router to storage."""
        self._route_observer = observer

    def _observe_route(self, event: ModelRouteEvent) -> None:
        if self._route_observer is not None:
            self._route_observer(event)

    def _report_success(self, candidate_id: str) -> None:
        reporter = getattr(self._router, "report_success", None)
        if callable(reporter):
            reporter(candidate_id)

    def _report_failure(self, candidate_id: str, error: str) -> None:
        reporter = getattr(self._router, "report_failure", None)
        if callable(reporter):
            reporter(candidate_id, error)
