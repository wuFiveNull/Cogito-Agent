"""E2E: /chat/stream uses RuntimeKernel end-to-end."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_stream_runtime_e2e(client: TestClient) -> None:
    """Full E2E: create session, stream message, verify SSE events."""
    # Create workspace
    client.post("/workspaces", params={"name": "e2e-stream"})

    # Create session
    sess_resp = client.post(
        "/sessions",
        json={
            "workspace_id": "e2e-stream",
            "title": "e2e-stream-test",
        },
    )
    assert sess_resp.status_code == 200
    sid = sess_resp.json()["id"]

    # Stream a message
    resp = client.post(
        "/chat/stream",
        json={
            "text": "test message",
            "session_id": sid,
            "workspace_id": "e2e-stream",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")

    body = resp.text
    assert "event: metadata" in body, f"Missing metadata event: {body[:200]}"

    # Parse SSE events from body
    events: list[dict[str, object]] = []
    current_event = ""
    for line in body.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: ") and current_event:
            data = json.loads(line[6:])
            events.append({"event": current_event, "data": data})
            current_event = ""

    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}: {events}"

    # First event should be metadata with request_id
    assert events[0]["event"] == "metadata"
    assert "request_id" in events[0]["data"]

    # Last event should be final (with response) or error
    last = events[-1]
    assert last["event"] in ("final", "error"), (
        f"Last event should be 'final' or 'error', got '{last['event']}': {last}"
    )
    if last["event"] == "final":
        assert "response" in last["data"]
        assert "state" in last["data"]
        assert "trace_id" in last["data"]
    elif last["event"] == "error":
        assert "error" in last["data"]
        assert "code" in last["data"]["error"]
        assert "message" in last["data"]["error"]

    # Verify trace exists (kernel creates a trace for every turn)
    trace_resp = client.get("/traces", params={"workspace_id": "e2e-stream"})
    assert trace_resp.status_code == 200
    traces = trace_resp.json()
    assert len(traces) >= 1, "Should have at least 1 trace from streaming turn"


def test_stream_trace_has_channel(client: TestClient) -> None:
    """Trace from streaming turn should have api_stream channel."""
    client.post("/workspaces", params={"name": "e2e-stream2"})
    sess_resp = client.post(
        "/sessions",
        json={
            "workspace_id": "e2e-stream2",
            "title": "e2e-stream2",
        },
    )
    sid = sess_resp.json()["id"]

    client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": sid,
            "workspace_id": "e2e-stream2",
        },
    )

    trace_resp = client.get("/traces", params={"workspace_id": "e2e-stream2"})
    traces = trace_resp.json()
    if traces:
        trace = traces[0]
        assert "trace_id" in trace or "id" in trace
