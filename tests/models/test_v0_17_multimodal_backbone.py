from __future__ import annotations

from collections.abc import Iterator

import pytest

from cogito_agent.models import (
    ModelAdapter,
    ModelCandidate,
    ModelResponse,
    ModelRouteErrorCode,
    ModelRouter,
    ModelRouteRequest,
    ProviderHealthStatus,
    RoutedModelAdapter,
)
from cogito_agent.models.messages import (
    ContentPart,
    FilePart,
    ImagePart,
    TextPart,
    extract_text,
    has_file,
    has_image,
    normalize_content,
)


class FakeAdapter:
    supports_streaming = True

    def __init__(self, *, content: str = "ok", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.provider = "fake"
        self.model = "fake-model"

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


def _candidate(
    provider: str,
    model: str = "m",
    *,
    candidate_id: str = "",
    capabilities: set[str] | None = None,
    roles: frozenset[str] | None = None,
    modalities: frozenset[str] | None = None,
    output_formats: frozenset[str] | None = None,
    quality_score: float = 0.5,
    priority: int = 100,
    enabled: bool = True,
) -> ModelCandidate:
    return ModelCandidate(
        candidate_id=candidate_id,
        provider=provider,
        model=model,
        capabilities=capabilities or {"chat"},
        roles=roles or frozenset({"chat"}),
        input_modalities=modalities or frozenset({"text"}),
        output_formats=output_formats or frozenset(),
        quality_score=quality_score,
        priority=priority,
        enabled=enabled,
    )


# ── 1. Normalize content / extract text ────────────────────────────────


def test_normalize_content_plain_string() -> None:
    parts = normalize_content("hello world")
    assert len(parts) == 1
    assert isinstance(parts[0], TextPart)
    assert parts[0].text == "hello world"


def test_normalize_content_empty_string() -> None:
    parts = normalize_content("")
    assert parts == []


def test_normalize_content_dict_list() -> None:
    parts = normalize_content([
        {"type": "text", "text": "hello"},
        {"type": "image", "uri": "data:image/png;base64,abc", "mime_type": "image/png"},
    ])
    assert len(parts) == 2
    assert isinstance(parts[0], TextPart)
    assert isinstance(parts[1], ImagePart)
    assert parts[1].mime_type == "image/png"


def test_normalize_content_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown content part type"):
        normalize_content([{"type": "audio", "data": "..."}])


def test_extract_text_concatenates() -> None:
    parts: list[ContentPart] = [
        TextPart(text="first"),
        ImagePart(uri="data:image/png;base64,a", mime_type="image/png"),
        TextPart(text="second"),
    ]
    assert extract_text(parts) == "first\nsecond"


def test_has_image_detection() -> None:
    parts: list[ContentPart] = [
        TextPart(text="hello"),
        ImagePart(uri="data:image/png;base64,a", mime_type="image/png"),
    ]
    assert has_image(parts)
    assert not has_file(parts)


def test_image_part_validates_uri_and_mime() -> None:
    with pytest.raises(ValueError, match="Unsupported image MIME type"):
        ImagePart(uri="file://img.bmp", mime_type="image/bmp")

    with pytest.raises(ValueError, match="Unsupported URI scheme"):
        ImagePart(uri="ftp://bad.com/img.png", mime_type="image/png")

    valid = ImagePart(uri="file://screenshot.png", mime_type="image/png")
    assert valid.uri == "file://screenshot.png"


# ── 2. ModelCandidate with explicit candidate_id ───────────────────────


def test_candidate_id_defaults_to_provider_model() -> None:
    c = ModelCandidate(provider="test", model="v1")
    assert c.id == "test:v1"


def test_candidate_id_explicit() -> None:
    c = ModelCandidate(candidate_id="my-vision", provider="test", model="v1")
    assert c.id == "my-vision"


def test_candidate_id_registered_in_router() -> None:
    c = _candidate("p", "m", candidate_id="my-candidate")
    router = ModelRouter([c])
    assert "my-candidate" in router._candidates


# ── 3. Image requests only select vision-capable candidates ────────────


def test_image_request_requires_vision_candidate() -> None:
    vision = _candidate(
        "vision-pro", "v1",
        capabilities={"chat", "vision"},
        modalities=frozenset({"text", "image"}),
    )
    text_only = _candidate("text-pro", "t1", capabilities={"chat"})
    router = ModelRouter([text_only, vision])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat", "vision"},
        required_input_modalities={"text", "image"},
    ))
    assert decision.selected is not None
    assert decision.selected.provider == "vision-pro"
    excluded_ids = [e.candidate_id for e in decision.exclusions]
    assert any("text-pro" in eid for eid in excluded_ids)


# ── 4. preferred_candidates affects sort order ──────────────────────────


def test_preferred_candidates_moves_to_front() -> None:
    a = _candidate("p1", "m1", priority=10)
    b = _candidate("p2", "m2", quality_score=0.9, priority=20)
    c = _candidate("p3", "m3", priority=30)
    router = ModelRouter([a, b, c])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        preferred_candidates=("p2:m2", "p3:m3"),
    ))
    assert decision.selected is not None
    assert decision.selected.id == "p2:m2"
    fallback_ids = [item.id for item in decision.fallback_order]
    assert fallback_ids == ["p3:m3", "p1:m1"]


def test_strict_preferred_candidates_excludes_others() -> None:
    preferred = _candidate("p1", "m1")
    other = _candidate("p2", "m2")
    router = ModelRouter([preferred, other])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        preferred_candidates=("p1:m1",),
        strict_preferred_candidates=True,
    ))
    assert decision.selected is not None
    assert decision.selected.id == "p1:m1"
    assert len(decision.fallback_order) == 0
    excluded_reasons = [e.reason_code for e in decision.exclusions]
    assert "not_preferred" in excluded_reasons


# ── 5. required_output_formats is strictly checked ─────────────────────


def test_required_output_formats_is_checked() -> None:
    text_only = _candidate("p1", "m1")
    with_json = _candidate(
        "p2", "m2",
        output_formats=frozenset({"text", "json"}),
    )
    router = ModelRouter([text_only, with_json])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        required_output_formats={"json"},
    ))
    assert decision.selected is not None
    assert decision.selected.id == "p2:m2"
    excluded_reasons = [e.reason_code for e in decision.exclusions]
    assert "missing_output_format" in excluded_reasons


# ── 6. Role mismatch is strict ────────────────────────────────────────


def test_role_mismatch_excludes_unrelated() -> None:
    planner = _candidate(
        "p1", "planner",
        roles=frozenset({"planner"}),
    )
    chat_only = _candidate("p2", "chat", roles=frozenset({"chat"}))
    router = ModelRouter([planner, chat_only])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        role="planner",
        chat_fallback_role=False,
    ))
    assert decision.selected is not None
    assert decision.selected.id == "p1:planner"
    excluded_reasons = [e.reason_code for e in decision.exclusions]
    assert "role_mismatch" in excluded_reasons


def test_chat_fallback_role_allows_generic_chat() -> None:
    planner = _candidate(
        "p1", "planner",
        roles=frozenset({"planner"}),
    )
    chat_only = _candidate("p2", "chat", roles=frozenset({"chat"}))
    router = ModelRouter([planner, chat_only])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        role="planner",
        chat_fallback_role=True,
    ))
    assert decision.selected is not None
    assert decision.selected.id == "p1:planner"


# ── 7. Health isolation at candidate_id level ──────────────────────────


def test_health_isolation_by_candidate_id() -> None:
    c1 = _candidate("p", "m1", candidate_id="cand-a")
    c2 = _candidate("p", "m2", candidate_id="cand-b")
    router = ModelRouter([c1, c2], failure_threshold=2, recovery_seconds=30)

    router.report_failure("cand-a", "timeout")
    router.report_failure("cand-a", "timeout again")

    assert router.get_health("cand-a").status == ProviderHealthStatus.unhealthy
    assert router.get_health("cand-b").status == ProviderHealthStatus.healthy

    decision = router.route(ModelRouteRequest(required_capabilities={"chat"}))
    assert decision.selected is not None
    assert decision.selected.id == "cand-b"


# ── 8. All vision candidates unavailable returns NO_VISION_MODEL_AVAILABLE ──


def test_all_vision_unavailable_returns_error_code() -> None:
    router = ModelRouter([
        _candidate(
            "vision", "v",
            capabilities={"chat", "vision"},
            modalities=frozenset({"text", "image"}),
            enabled=False,
        ),
    ])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat", "vision"},
        required_input_modalities={"text", "image"},
    ))
    assert decision.selected is None
    assert decision.error_code == ModelRouteErrorCode.NO_VISION_MODEL_AVAILABLE


def test_no_eligible_returns_no_model_candidate() -> None:
    router = ModelRouter([])
    decision = router.route(ModelRouteRequest(required_capabilities={"chat"}))
    assert decision.selected is None
    assert decision.error_code == ModelRouteErrorCode.NO_MODEL_CANDIDATE


def test_no_structured_output_returns_correct_code() -> None:
    router = ModelRouter([
        _candidate("p", "m", output_formats=frozenset({"text"})),
    ])
    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        required_output_formats={"json"},
    ))
    assert decision.selected is None
    assert decision.error_code == ModelRouteErrorCode.NO_STRUCTURED_OUTPUT_MODEL


# ── 9. Streaming uses same routing logic ──────────────────────────────


def test_streaming_uses_same_routing() -> None:
    vision = _candidate(
        "vision", "v",
        capabilities={"chat", "vision"},
        modalities=frozenset({"text", "image"}),
    )
    router = ModelRouter([vision])
    adapters = {"vision:v": FakeAdapter(content="streamed vision result")}
    routed = RoutedModelAdapter(router, lambda c: adapters[c.id])

    chunks = list(routed.stream_chat([
        {"role": "user", "content": [
            {"type": "image", "uri": "file://img.png", "mime_type": "image/png"},
        ]},
    ]))
    assert len(chunks) == 1
    assert "vision" in chunks[0]


def test_routed_adapter_includes_error_code() -> None:
    router = ModelRouter([])
    routed = RoutedModelAdapter(router, lambda c: FakeAdapter())

    with pytest.raises(RuntimeError, match=ModelRouteErrorCode.NO_MODEL_CANDIDATE.value):
        routed.chat([{"role": "user", "content": "hello"}])

    with pytest.raises(RuntimeError, match=ModelRouteErrorCode.NO_MODEL_CANDIDATE.value):
        list(routed.stream_chat([{"role": "user", "content": "hello"}]))


# ── 10. Modality strictness: always check, not just for non-text ──────


def test_modality_check_is_always_strict() -> None:
    """Modality check should run even when required is just {text}."""
    text_only = _candidate("p", "m", modalities=frozenset({"text"}))
    image_capable = _candidate(
        "q", "v",
        capabilities={"chat", "vision"},
        modalities=frozenset({"text", "image"}),
    )
    router = ModelRouter([text_only, image_capable])

    decision = router.route(ModelRouteRequest(
        required_capabilities={"chat", "vision"},
        required_input_modalities={"text", "image"},
    ))
    assert decision.selected is not None
    assert "q" in decision.selected.provider

    # Text-only request should still work
    text_decision = router.route(ModelRouteRequest(
        required_capabilities={"chat"},
        required_input_modalities={"text"},
    ))
    assert text_decision.selected is not None
    assert "p" in text_decision.selected.provider
