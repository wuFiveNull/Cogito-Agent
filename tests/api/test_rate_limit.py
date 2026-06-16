from __future__ import annotations

import json as _json
import os
import sys as _sys
import time
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import cogito_agent.api.app as _  # Ensure module is loaded into sys.modules
_app_module = _sys.modules["cogito_agent.api.app"]


def _clear_rate_limiter() -> None:
    _app_module._RATE_LIMITER.clear()


def test_rate_limit_disabled_by_default() -> None:
    _clear_rate_limiter()
    client = TestClient(_app_module.app)
    for _ in range(20):
        resp = client.get("/workspaces")
        assert resp.status_code != 429


def test_check_rate_limit_exceeded() -> None:
    _clear_rate_limiter()
    with patch.dict(
        os.environ,
        {"COGITO_RATE_LIMIT_ENABLED": "1", "COGITO_RATE_LIMIT_PER_MINUTE": "1"},
        clear=True,
    ):
        mock_request = Mock()
        mock_request.client.host = "test-client"
        assert _app_module._check_rate_limit(mock_request) is True
        assert _app_module._check_rate_limit(mock_request) is False


def test_check_rate_limit_disabled() -> None:
    _clear_rate_limiter()
    mock_request = Mock()
    mock_request.client.host = "test-client"
    for _ in range(100):
        assert _app_module._check_rate_limit(mock_request) is True


def test_check_rate_limit_window_expiry() -> None:
    _clear_rate_limiter()
    with patch.dict(
        os.environ,
        {"COGITO_RATE_LIMIT_ENABLED": "1", "COGITO_RATE_LIMIT_PER_MINUTE": "1"},
        clear=True,
    ):
        mock_request = Mock()
        mock_request.client.host = "test-client"
        assert _app_module._check_rate_limit(mock_request) is True
        assert _app_module._check_rate_limit(mock_request) is False

        _clear_rate_limiter()
        assert _app_module._check_rate_limit(mock_request) is True


def test_rate_limited_error_schema() -> None:
    resp = _app_module._error_response(
        "RATE_LIMITED", "Rate limit exceeded", "req-123",
        retryable=True, status_code=429,
    )
    assert resp.status_code == 429
    data = _json.loads(resp.body)
    err = data["error"]
    assert err["code"] == "RATE_LIMITED"
    assert err["message"] == "Rate limit exceeded"
    assert err["request_id"] == "req-123"
    assert err["trace_id"] is None
    assert err["retryable"] is True
