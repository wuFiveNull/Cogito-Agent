from __future__ import annotations

import json as _json
import os
import sys as _sys
from unittest.mock import patch

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

import cogito_agent.api.app as _  # Ensure module is loaded into sys.modules
_app_module = _sys.modules["cogito_agent.api.app"]


def test_validation_error_returns_correct_schema() -> None:
    client = TestClient(app)
    resp = client.post("/chat", json={"text": "hello", "session_id": 123, "workspace_id": "ws"})
    assert resp.status_code == 422
    data = resp.json()
    err = data["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert isinstance(err["message"], str)
    assert len(err["message"]) > 0
    assert isinstance(err["request_id"], str)
    assert err["trace_id"] is None
    assert err["retryable"] is False


def test_not_found_returns_correct_schema() -> None:
    client = TestClient(app)
    resp = client.get("/workspaces/nonexistent")
    assert resp.status_code == 404
    data = resp.json()
    err = data["error"]
    assert err["code"] == "NOT_FOUND"
    assert isinstance(err["message"], str)
    assert len(err["message"]) > 0
    assert isinstance(err["request_id"], str)
    assert err["trace_id"] is None
    assert err["retryable"] is False


def test_internal_error_returns_correct_schema() -> None:
    resp = _app_module._error_response(
        "INTERNAL_ERROR", "Internal server error", "req-123",
        trace_id="trace-456", retryable=False, status_code=500,
    )
    assert resp.status_code == 500
    data = _json.loads(resp.body)
    err = data["error"]
    assert err["code"] == "INTERNAL_ERROR"
    assert err["message"] == "Internal server error"
    assert err["request_id"] == "req-123"
    assert err["trace_id"] == "trace-456"
    assert err["retryable"] is False


def test_internal_error_message_redacted() -> None:
    resp = _app_module._error_response(
        "INTERNAL_ERROR", "Bearer sk-secret-key-123456", "req-1", status_code=500,
    )
    data = _json.loads(resp.body)
    assert "[REDACTED]" in data["error"]["message"]
    assert "sk-secret-key-123456" not in data["error"]["message"]


def test_unauthorized_returns_correct_schema() -> None:
    with patch.dict(os.environ, {"COGITO_API_KEY": "secret123"}, clear=True):
        client = TestClient(app)
        resp = client.get("/workspaces")
        assert resp.status_code == 401
        data = resp.json()
        err = data["error"]
        assert err["code"] == "UNAUTHORIZED"
        assert err["message"] == "Unauthorized"
        assert isinstance(err["request_id"], str)
        assert err["trace_id"] is None
        assert err["retryable"] is False


def test_error_response_includes_x_request_id_header() -> None:
    client = TestClient(app)
    resp = client.get("/workspaces/nonexistent")
    assert resp.status_code == 404
    assert "X-Request-ID" in resp.headers
    rid = resp.headers["X-Request-ID"]
    assert isinstance(rid, str)
    assert len(rid) > 0
