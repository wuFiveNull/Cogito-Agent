"""Tests: /chat/stream uses RuntimeKernel with SSE events."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.registry import ToolResult
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.shared.manifests import (
    CapabilityManifest,
    CapabilityType,
    RiskLevel,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _setup(client: TestClient) -> tuple[str, str]:
    resp = client.post("/workspaces", params={"name": "ws-stream"}, json={})
    assert resp.status_code in {200, 409}
    resp = client.post(
        "/sessions",
        json={
            "workspace_id": "ws-stream",
            "title": "stream-test",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    return "ws-stream", data["id"]


def test_chat_stream_uses_runtime_kernel(client: TestClient) -> None:
    """Verify /chat/stream now uses RuntimeKernel (not bypassing it)."""
    _, sid = _setup(client)
    resp = client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": sid,
            "workspace_id": "ws-stream",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    assert "X-Experimental" not in resp.headers, "Should not have bypass header"


def test_chat_stream_metadata_event(client: TestClient) -> None:
    """Stream outputs metadata event with request_id."""
    _, sid = _setup(client)
    resp = client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": sid,
            "workspace_id": "ws-stream",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    assert "event: metadata" in body
    assert "request_id" in body


def _get_api_mod():
    """Get module object despite __init__.py shadowing."""
    return sys.modules.get("cogito_agent.api.app")


def _reset_kernel():
    """Reset module-level kernel so each test starts fresh."""
    mod = _get_api_mod()
    if mod:
        mod._kernel = None


def _sse_parse(text: str) -> list[dict[str, object]]:
    """Parse SSE text into [{event, data}, ...]."""
    events: list[dict[str, object]] = []
    cur_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            cur_event = line[7:]
        elif line.startswith("data: "):
            events.append({"event": cur_event, "data": json.loads(line[6:])})
            cur_event = ""
    return events


def test_chat_stream_final_event(client: TestClient) -> None:
    """Stream outputs final event with response."""
    _reset_kernel()
    _, sid = _setup(client)
    resp = client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": sid,
            "workspace_id": "ws-stream",
        },
    )
    assert resp.status_code == 200
    events = _sse_parse(resp.text)
    final = [e for e in events if e["event"] == "final"]
    assert len(final) == 1, f"Expected 1 final event, got {len(final)}"
    payload = final[0]["data"]
    assert "response" in payload
    assert "state" in payload
    assert payload["response"], "response should be non-empty"


def test_chat_stream_no_session(client: TestClient) -> None:
    """Stream returns 404 for nonexistent session."""
    _reset_kernel()
    resp = client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": "nonexistent",
            "workspace_id": "ws-stream",
        },
    )
    assert resp.status_code == 404


def test_chat_stream_no_experimental_gate(client: TestClient) -> None:
    """Stream no longer requires COGITO_ENABLE_EXPERIMENTAL gate."""
    _reset_kernel()
    _, sid = _setup(client)
    resp = client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": sid,
            "workspace_id": "ws-stream",
        },
    )
    assert resp.status_code == 200, "Should work without experimental gate"


def test_chat_stream_response_is_redacted(client: TestClient) -> None:
    """Stream output should be redacted (safe)."""
    _reset_kernel()
    _, sid = _setup(client)
    resp = client.post(
        "/chat/stream",
        json={
            "text": "hello",
            "session_id": sid,
            "workspace_id": "ws-stream",
        },
    )
    assert resp.status_code == 200
    body = resp.text
    events = _sse_parse(body)
    final = [e for e in events if e["event"] == "final"]
    assert len(final) >= 1, f"No final event found in: {body[:200]}"
    assert "Bearer" not in body
    assert "Authorization" not in body


def test_chat_stream_approval_required_event() -> None:
    """Stream outputs approval_required event with approval_id and trace_id."""
    api_mod = _get_api_mod()
    _reset_kernel()
    original_kernel = getattr(api_mod, "_kernel", None)

    # Register a capability that requires approval
    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "write_file",
        CapabilityManifest(
            name="write_file",
            version="1.0.0",
            type=CapabilityType.tool,
            description="Write a file",
            input_schema={},
            output_schema={},
            permissions=[],
            risk_level=RiskLevel.medium,
            allowed_contexts=["interactive"],
            approval_required=True,
            audit_required=True,
            idempotent=False,
        ),
        lambda **kw: ToolResult(status="ok", summary="written"),
    )

    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="writing file now",
        tool_intents=[{"name": "write_file", "arguments": {}}],
    )

    custom_kernel = RuntimeKernel(
        getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db(),
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
    )
    api_mod._kernel = custom_kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            sresp = c.post("/sessions", json={"workspace_id": "ws-approval", "title": "t"})
            sid = str(sresp.json().get("id", ""))
            resp = c.post(
                "/chat/stream",
                json={
                    "text": "write file",
                    "session_id": sid,
                    "workspace_id": "ws-approval",
                },
            )
            assert resp.status_code == 200
            body = resp.text
            assert "event: approval_required" in body
            lines = body.strip().split("\n")
            payload = None
            for i, line in enumerate(lines):
                if line == "event: approval_required":
                    data_line = lines[i + 1] if i + 1 < len(lines) else ""
                    if data_line.startswith("data: "):
                        payload = json.loads(data_line[6:])
                        break
            assert payload is not None, "No data line after approval_required event"
            assert "approval_id" in payload, "approval_required data missing approval_id"
            assert "trace_id" in payload, "approval_required data missing trace_id"
            assert payload["approval_id"], "approval_id must be non-empty"
            assert payload["trace_id"], "trace_id must be non-empty"
    finally:
        api_mod._kernel = original_kernel
