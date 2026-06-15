from .adapter import ModelAdapter, ModelResponse
from .openai_adapter import OpenAICompatibleAdapter
from .registry import ProviderConfig, get_adapter, list_providers, register_provider

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
    "OpenAICompatibleAdapter",
    "ProviderConfig",
    "get_adapter",
    "list_providers",
    "register_provider",
    "token_count",
]
