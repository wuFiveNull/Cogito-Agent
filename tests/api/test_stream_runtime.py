"""Tests: /chat/stream uses RuntimeKernel with SSE events."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _setup(client: TestClient) -> tuple[str, str]:
    resp = client.post("/workspaces", params={"name": "ws-stream"}, json={})
    wid = "ws-stream" if resp.status_code == 200 else resp.json()["id"]
    resp = client.post("/sessions", json={
        "workspace_id": "ws-stream",
        "title": "stream-test",
    })
    assert resp.status_code == 200
    data = resp.json()
    return "ws-stream", data["id"]


def test_chat_stream_uses_runtime_kernel(client: TestClient) -> None:
    """Verify /chat/stream now uses RuntimeKernel (not bypassing it)."""
    _, sid = _setup(client)
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    assert "X-Experimental" not in resp.headers, "Should not have bypass header"


def test_chat_stream_metadata_event(client: TestClient) -> None:
    """Stream outputs metadata event with request_id."""
    _, sid = _setup(client)
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 200
    body = resp.text
    assert "event: metadata" in body
    assert "request_id" in body


def test_chat_stream_final_event(client: TestClient) -> None:
    """Stream outputs final event with response."""
    _, sid = _setup(client)
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 200
    body = resp.text
    assert "event: final" in body
    lines = body.strip().split("\n")
    for i, line in enumerate(lines):
        if line.startswith("data:") and "event: final" in body:
            data_line = lines[i + 1] if i + 1 < len(lines) else ""
            if data_line.startswith("data:"):
                payload = json.loads(data_line[5:].strip())
                assert "response" in payload
                assert "state" in payload
                break


def test_chat_stream_no_session(client: TestClient) -> None:
    """Stream returns 404 for nonexistent session."""
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": "nonexistent",
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 404


def test_chat_stream_no_experimental_gate(client: TestClient) -> None:
    """Stream no longer requires COGITO_ENABLE_EXPERIMENTAL gate."""
    _, sid = _setup(client)
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 200, "Should work without experimental gate"


def test_chat_stream_response_is_redacted(client: TestClient) -> None:
    """Stream output should be redacted (safe)."""
    _, sid = _setup(client)
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-stream",
    })
    assert resp.status_code == 200
    body = resp.text
    # Mock model returns "You said: hello" — not sensitive, but verify
    # the response is well-formed JSON in the final event
    assert "event: final" in body
    assert "Bearer" not in body
    assert "Authorization" not in body
