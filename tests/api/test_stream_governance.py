"""Tests: Streaming governance — approval_required, policy deny, tool calls."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.registry import ToolResult
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import DecisionType
from cogito_agent.shared.manifests import (
    CapabilityManifest,
    CapabilityType,
    Permission,
    RiskLevel,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def ws_session(client: TestClient) -> tuple[str, str]:
    """Create workspace + session via the API for the global DB."""
    client.post("/workspaces", params={"name": "ws-gov"}, json={})
    resp = client.post("/sessions", json={
        "workspace_id": "ws-gov", "title": "gov-test",
    })
    return "ws-gov", resp.json()["id"]


def _cap_manifest(name: str = "test_tool") -> CapabilityManifest:
    return CapabilityManifest(
        name=name, version="1.0", type=CapabilityType.tool,
        description="Test",
        input_schema={"type": "object", "properties": {"input_text": {"type": "string"}}},
        output_schema={},
        permissions=[Permission(resource="*", operations=["execute"])],
        risk_level=RiskLevel.low,
        allowed_contexts=["interactive", "background"],
        approval_required=True,
        audit_required=True,
        idempotent=True,
    )


def _sse_parse(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    cur_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            cur_event = line[7:]
        elif line.startswith("data: "):
            try:
                events.append({"event": cur_event, "data": json.loads(line[6:])})
            except json.JSONDecodeError:
                events.append({"event": cur_event, "data": {}})
            cur_event = ""
    return events


def _get_api_mod():
    return sys.modules.get("cogito_agent.api.app")


def _reset_kernel():
    mod = _get_api_mod()
    if mod:
        mod._kernel = None


def test_stream_approval_required_event(client: TestClient, ws_session: tuple[str, str]) -> None:
    """Stream outputs approval_required event when capability requires approval."""
    _reset_kernel()
    api_mod = _get_api_mod()
    wid, sid = ws_session

    cap_reg = CapabilityRegistry()
    cap_reg.register("write_file", _cap_manifest("write_file"),
                     lambda **kw: ToolResult(status="ok", summary="written"))

    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="writing file now",
        tool_intents=[{"name": "write_file", "arguments": {}}],
    )

    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(
        shared_db,
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
    )
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post("/chat/stream", json={
                "text": "write file", "session_id": sid, "workspace_id": wid,
            })
            assert resp.status_code == 200
            assert "event: approval_required" in resp.text
    finally:
        api_mod._kernel = None


def test_stream_policy_deny_error(client: TestClient, ws_session: tuple[str, str]) -> None:
    """Stream outputs error event when policy denies the model call."""
    _reset_kernel()
    api_mod = _get_api_mod()
    wid, sid = ws_session

    policy = PolicyEngine(rules=[
        PolicyRule("*", "call_model", "*", DecisionType.deny),
    ])
    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(shared_db, policy_engine=policy)
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post("/chat/stream", json={
                "text": "hello", "session_id": sid, "workspace_id": wid,
            })
            assert resp.status_code == 200
            assert "POLICY_DENIED" in resp.text
    finally:
        api_mod._kernel = None
