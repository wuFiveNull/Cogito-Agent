from __future__ import annotations

from cogito_agent.models import ProviderConfig, get_adapter, list_providers, register_provider


def test_default_providers_exist() -> None:
    provs = list_providers()
    assert "openai" in provs
    assert "ollama" in provs
    assert "deepseek" in provs


def test_register_custom_provider() -> None:
    cfg = ProviderConfig("test-provider", base_url="http://test", default_model="test-model")
    register_provider(cfg)
    assert "test-provider" in list_providers()


def test_get_adapter_openai() -> None:
    adapter = get_adapter(provider="openai", model="gpt-4")
    assert adapter.model == "gpt-4"
    assert "api.openai.com" in adapter.base_url


def test_get_adapter_ollama() -> None:
    adapter = get_adapter(provider="ollama", model="llama3.2")
    assert "llama3.2" in adapter.model
    assert "localhost:11434" in adapter.base_url


def test_get_adapter_unknown_fallback() -> None:
    adapter = get_adapter(provider="nonexistent", model="custom-model")
    assert adapter.model == "custom-model"
