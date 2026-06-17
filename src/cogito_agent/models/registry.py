from __future__ import annotations

import os

from .adapter import ModelResponse  # noqa: F401
from .openai_adapter import OpenAICompatibleAdapter


class ProviderConfig:
    def __init__(
        self,
        name: str,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o-mini",
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model


_PROVIDERS: dict[str, ProviderConfig] = {}


def register_provider(config: ProviderConfig) -> None:
    _PROVIDERS[config.name] = config


def get_adapter(
    provider: str = "openai",
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    timeout_sec: int = 60,
) -> OpenAICompatibleAdapter:
    cfg = _PROVIDERS.get(provider)
    if cfg is None:
        cfg = ProviderConfig(
            name=provider,
            api_key=os.environ.get("MODEL_API_KEY", ""),
            base_url=os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
            default_model=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
        )
    return OpenAICompatibleAdapter(
        api_key=api_key or cfg.api_key or os.environ.get("MODEL_API_KEY", ""),
        base_url=base_url or cfg.base_url or os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
        model=model or cfg.default_model or os.environ.get("MODEL_NAME", "gpt-4o-mini"),
        timeout_sec=timeout_sec,
    )


def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())


register_provider(ProviderConfig(
    name="openai",
    api_key=os.environ.get("OPENAI_API_KEY", ""),
    base_url="https://api.openai.com/v1",
    default_model="gpt-4o-mini",
))

register_provider(ProviderConfig(
    name="ollama",
    api_key="",
    base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    default_model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
))

register_provider(ProviderConfig(
    name="deepseek",
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com/v1",
    default_model="deepseek-chat",
))
