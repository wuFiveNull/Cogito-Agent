from collections.abc import Callable

from .adapter import ModelAdapter, ModelResponse, StreamGenerator, ToolIntent
from .messages import (
    ChatMessage,
    ContentPart,
    ContentPartType,
    FilePart,
    ImagePart,
    MessageRole,
    TextPart,
    extract_text,
    has_file,
    has_image,
    normalize_content,
)
from .registry import ProviderConfig, get_adapter, list_providers, register_provider
from .router import (
    ModelCandidate,
    ModelExclusion,
    ModelRole,
    ModelRouteDecision,
    ModelRouteErrorCode,
    ModelRouteEvent,
    ModelRouteEventType,
    ModelRouter,
    ModelRouteRequest,
    ModelRouterProtocol,
    ProviderHealth,
    ProviderHealthStatus,
    RoutedModelAdapter,
)
from .vision import VisionObservation, render_observation_as_text


# Lazy imports for modules with potential circular dependencies
def _import_codec() -> dict[str, object]:
    from .codec import (
        GeminiCodec,
        OpenAICompatibleCodec,
        ProviderMessageCodec,
        TextOnlyCodec,
        UnsupportedModalityError,
        get_codec_for_provider,
    )
    return {
        "GeminiCodec": GeminiCodec,
        "OpenAICompatibleCodec": OpenAICompatibleCodec,
        "ProviderMessageCodec": ProviderMessageCodec,
        "TextOnlyCodec": TextOnlyCodec,
        "UnsupportedModalityError": UnsupportedModalityError,
        "get_codec_for_provider": get_codec_for_provider,
    }

def _import_orchestrator() -> dict[str, object]:
    from .orchestrator import (
        ExecutionStep,
        OrchestrationPlan,
        TaskKind,
        TaskOrchestrator,
    )
    return {
        "ExecutionStep": ExecutionStep,
        "OrchestrationPlan": OrchestrationPlan,
        "TaskKind": TaskKind,
        "TaskOrchestrator": TaskOrchestrator,
    }

def _import_provider_errors() -> dict[str, object]:
    from .provider_errors import ProviderError, ProviderErrorCode
    return {
        "ProviderError": ProviderError,
        "ProviderErrorCode": ProviderErrorCode,
    }

def _import_analyze_image() -> object:
    from .vision import analyze_image
    return analyze_image


def _import_openai_adapter() -> type:
    from .openai_adapter import OpenAICompatibleAdapter
    return OpenAICompatibleAdapter  # type: ignore[return-value]


def __getattr__(name: str) -> object:
    _lazy_map: dict[str, Callable[..., object]] = {
        "GeminiCodec": _import_codec,
        "OpenAICompatibleCodec": _import_codec,
        "ProviderMessageCodec": _import_codec,
        "TextOnlyCodec": _import_codec,
        "UnsupportedModalityError": _import_codec,
        "get_codec_for_provider": _import_codec,
        "ExecutionStep": _import_orchestrator,
        "OrchestrationPlan": _import_orchestrator,
        "TaskKind": _import_orchestrator,
        "TaskOrchestrator": _import_orchestrator,
        "ProviderError": _import_provider_errors,
        "ProviderErrorCode": _import_provider_errors,
        "analyze_image": _import_analyze_image,
        "OpenAICompatibleAdapter": _import_openai_adapter,
    }
    loader = _lazy_map.get(name)
    if loader is not None:
        result = loader()
        if isinstance(result, dict):
            return result[name]
        return result
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


try:
    import tiktoken

    _tokenizer = tiktoken.get_encoding("cl100k_base")

    def token_count(text: str) -> int:
        return len(_tokenizer.encode(text))

except ImportError:

    def token_count(text: str) -> int:
        return max(1, len(text) // 4)


__all__ = [
    "ModelAdapter",
    "ModelResponse",
    "StreamGenerator",
    "ToolIntent",
    "OpenAICompatibleAdapter",
    "ProviderConfig",
    "get_adapter",
    "list_providers",
    "ModelCandidate",
    "ModelExclusion",
    "ModelRole",
    "ModelRouteDecision",
    "ModelRouteErrorCode",
    "ModelRouteEvent",
    "ModelRouteEventType",
    "ModelRouteRequest",
    "ModelRouter",
    "ModelRouterProtocol",
    "ProviderHealth",
    "ProviderHealthStatus",
    "RoutedModelAdapter",
    "register_provider",
    "token_count",
    "ProviderMessageCodec",
    "TextOnlyCodec",
    "OpenAICompatibleCodec",
    "GeminiCodec",
    "UnsupportedModalityError",
    "get_codec_for_provider",
    "VisionObservation",
    "analyze_image",
    "render_observation_as_text",
    "TaskKind",
    "ExecutionStep",
    "OrchestrationPlan",
    "TaskOrchestrator",
    "ProviderError",
    "ProviderErrorCode",
    "ChatMessage",
    "ContentPart",
    "ContentPartType",
    "FilePart",
    "ImagePart",
    "MessageRole",
    "TextPart",
    "extract_text",
    "has_file",
    "has_image",
    "normalize_content",
]
