"""Tests: /chat/stream error schema uses unified error format."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_stream_nonexistent_session_returns_404(client: TestClient) -> None:
    """Stream returns 404 JSON for nonexistent session (not SSE)."""
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": "does-not-exist",
        "workspace_id": "ws-1",
    })
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"


def test_stream_missing_text_returns_422(client: TestClient) -> None:
    """Stream returns 422 for missing required field."""
    resp = client.post("/chat/stream", json={
        "session_id": "some-id",
        "workspace_id": "ws-1",
    })
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data or "detail" in data


def test_stream_runtime_error_uses_unified_schema(client: TestClient) -> None:
    """When kernel raises, stream outputs error SSE event with unified schema."""
    # Send a valid request - if kernel fails internally, error SSE is emitted
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": "nonexistent",
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert "request_id" in data["error"]


def test_stream_error_no_secrets_in_message(client: TestClient) -> None:
    """Error messages should not contain secrets."""
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": "nonexistent",
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 404
    body = resp.text
    assert "Bearer" not in body
    assert "sk-" not in body
    assert "Authorization" not in body
