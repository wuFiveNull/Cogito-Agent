from __future__ import annotations

from cogito_agent.models import (
    ModelCandidate,
    ModelRouter,
    ModelRouteRequest,
    ProviderHealthStatus,
)


def _candidate(provider: str, model: str, **overrides: object) -> ModelCandidate:
    values: dict[str, object] = {
        "provider": provider,
        "model": model,
        "capabilities": {"chat", "tools"},
        "context_window": 16_000,
        "quality_score": 0.8,
        "expected_latency_ms": 500,
        "input_cost_per_million": 1.0,
        "output_cost_per_million": 2.0,
    }
    values.update(overrides)
    return ModelCandidate.model_validate(values)


def test_router_honors_preference_and_returns_fallbacks() -> None:
    router = ModelRouter([_candidate("local", "fast"), _candidate("cloud", "quality")])

    decision = router.route(
        ModelRouteRequest(
            required_capabilities={"chat"},
            preferred_provider="cloud",
        )
    )

    assert decision.selected is not None
    assert decision.selected.id == "cloud:quality"
    assert [item.id for item in decision.fallback_order] == ["local:fast"]


def test_router_explains_all_constraint_exclusions() -> None:
    router = ModelRouter(
        [
            _candidate("disabled", "m", enabled=False),
            _candidate("small", "m", context_window=100),
            _candidate("limited", "m", capabilities={"chat"}),
            _candidate("slow", "m", expected_latency_ms=5000),
            _candidate("expensive", "m", input_cost_per_million=1000.0),
        ]
    )

    decision = router.route(
        ModelRouteRequest(
            required_capabilities={"chat", "tools"},
            estimated_input_tokens=200,
            max_output_tokens=100,
            max_latency_ms=1000,
            max_cost_usd=0.01,
        )
    )

    assert decision.selected is None
    assert {item.reason_code for item in decision.exclusions} == {
        "disabled",
        "context_window",
        "missing_capability",
        "latency",
        "budget",
    }


def test_router_circuit_breaker_and_recovery_probe() -> None:
    now = [100.0]
    router = ModelRouter(
        [_candidate("primary", "m"), _candidate("fallback", "m")],
        failure_threshold=2,
        recovery_seconds=10,
        clock=lambda: now[0],
    )
    router.report_failure("primary:m", "timeout")
    health = router.report_failure("primary:m", "timeout")
    assert health.status == ProviderHealthStatus.unhealthy

    open_decision = router.route(ModelRouteRequest(preferred_provider="primary"))
    assert open_decision.selected is not None
    assert open_decision.selected.provider == "fallback"
    assert any(item.reason_code == "circuit_open" for item in open_decision.exclusions)

    now[0] = 111.0
    probe = router.route(ModelRouteRequest(preferred_provider="primary"))
    assert probe.selected is not None
    assert probe.selected.provider == "primary"
    assert router.get_health("primary:m").status == ProviderHealthStatus.probing

    router.report_success("primary:m")
    assert router.get_health("primary:m").status == ProviderHealthStatus.healthy


def test_router_is_deterministic_for_equal_candidates() -> None:
    router = ModelRouter([_candidate("z", "m"), _candidate("a", "m")])
    decisions = [router.route(ModelRouteRequest()).selected for _ in range(5)]
    assert all(candidate is not None and candidate.id == "a:m" for candidate in decisions)
