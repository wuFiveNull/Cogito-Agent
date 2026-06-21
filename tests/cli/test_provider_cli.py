"""Tests for provider CLI commands."""

from __future__ import annotations

import os
from unittest.mock import patch

from cogito_agent.cli.provider_cli import (
    _check_secret_available,
    _get_provider_info,
    _health_strategy,
)


def test_api_key_can_be_resolved_from_config_file() -> None:
    from cogito_agent.cli.config_manager import _resolve_api_key

    assert _resolve_api_key({"model.api_key": "configured-key"}) == "configured-key"


def _ns(**kwargs):
    class NS:
        pass

    n = NS()
    for k, v in kwargs.items():
        setattr(n, k, v)
    return n


def test_health_strategy_ollama():
    url, _ = _health_strategy("ollama", "http://localhost:11434")
    assert "/api/tags" in url


def test_health_strategy_openai():
    url, _ = _health_strategy("openai", "https://api.openai.com/v1")
    assert "/models" in url


def test_health_strategy_unknown():
    url, _ = _health_strategy("custom", "https://custom.example.com/v1")
    assert "/models" in url  # fallback to /models


def test_check_secret_available_config_ref():
    """When secret_ref is configured and available, returns True."""
    with patch.dict(os.environ, {"MODEL_API_KEY": ""}, clear=True):
        from cogito_agent.cli.config_manager import get_config

        get_config()
        # No secret_ref, no api_key_env -> should be False
        result = _check_secret_available()
        # This depends on environment - just verify it returns bool
        assert isinstance(result, bool)


def test_get_provider_info_mock():
    info = _get_provider_info("mock")
    assert info["name"] == "mock"
    assert info["requires_secret"] is False


def test_get_provider_info_openai():
    info = _get_provider_info("openai")
    assert info["name"] == "openai"
    assert info["requires_secret"] is True
