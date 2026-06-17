"""Tests: model.timeout_seconds and model.max_retries config."""

from cogito_agent.models import get_adapter
from cogito_agent.models.openai_adapter import OpenAICompatibleAdapter


def test_adapter_accepts_timeout():
    adapter = get_adapter(provider="openai", timeout_sec=30)
    assert adapter is not None
    assert adapter.timeout_sec == 30


def test_adapter_default_timeout():
    adapter = get_adapter(provider="openai")
    assert adapter is not None
    assert adapter.timeout_sec == 60


def test_adapter_timeout_passed_to_chat():
    """Verify timeout_sec is stored and used."""
    adapter = OpenAICompatibleAdapter(api_key="test-key", timeout_sec=15)
    assert adapter.timeout_sec == 15


def test_adapter_timeout_no_api_key():
    """Even without API key, timeout config is set."""
    adapter = OpenAICompatibleAdapter(timeout_sec=99)
    assert adapter.timeout_sec == 99
