from .adapter import ModelAdapter, ModelResponse, StreamGenerator, ToolIntent
from .openai_adapter import OpenAICompatibleAdapter
from .registry import ProviderConfig, get_adapter, list_providers, register_provider
from .router import (
    ModelCandidate,
    ModelExclusion,
    ModelRole,
    ModelRouteDecision,
    ModelRouteEvent,
    ModelRouteEventType,
    ModelRouter,
    ModelRouteRequest,
    ModelRouterProtocol,
    ProviderHealth,
    ProviderHealthStatus,
    RoutedModelAdapter,
)
from .codec import (
    ProviderMessageCodec,
    TextOnlyCodec,
    OpenAICompatibleCodec,
    GeminiCodec,
    UnsupportedModalityError,
    get_codec_for_provider,
)
from .vision import VisionObservation, analyze_image, render_observation_as_text
from .orchestrator import (
    TaskKind,
    ExecutionStep,
    OrchestrationPlan,
    TaskOrchestrator,
)
from .provider_errors import ProviderError, ProviderErrorCode

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
]
