"""Tests: Redaction in /chat/stream SSE output.

Verifies that secrets are redacted from delta, error, and final events.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.application import build_runtime_kernel as RuntimeKernel  # noqa: N812
from cogito_agent.capability import CapabilityRegistry
from cogito_agent.capability.registry import ToolResult
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.shared import DecisionType
from cogito_agent.shared.manifests import (
    CapabilityManifest,
    CapabilityType,
    Permission,
    RiskLevel,
)
from tests.models.mock_model import MockModel


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def ws_session(client: TestClient) -> tuple[str, str]:
    client.post("/workspaces", params={"name": "ws-redact"}, json={})
    resp = client.post(
        "/sessions",
        json={
            "workspace_id": "ws-redact",
            "title": "redact-test",
        },
    )
    return "ws-redact", resp.json()["id"]


def _get_api_mod():
    return sys.modules.get("cogito_agent.api.app")


def test_stream_redacts_bearer_token_in_delta(
    client: TestClient, ws_session: tuple[str, str]
) -> None:
    """Delta events should redact Bearer tokens."""
    api_mod = _get_api_mod()
    if api_mod:
        api_mod._kernel = None
    wid, sid = ws_session

    adapter = MockModel(response_text="My token is Bearer sk-test-secret-12345")
    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(shared_db, model_adapter=adapter)
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post(
                "/chat/stream",
                json={
                    "text": "hello",
                    "session_id": sid,
                    "workspace_id": wid,
                },
            )
            assert resp.status_code == 200
            assert "sk-test-secret-12345" not in resp.text
    finally:
        api_mod._kernel = None


def test_stream_redacts_bearer_token_in_final(
    client: TestClient, ws_session: tuple[str, str]
) -> None:
    """Final event should redact Bearer tokens."""
    api_mod = _get_api_mod()
    if api_mod:
        api_mod._kernel = None
    wid, sid = ws_session

    adapter = MockModel(response_text="My token is Bearer sk-another-secret")
    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(shared_db, model_adapter=adapter)
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post(
                "/chat/stream",
                json={
                    "text": "hello",
                    "session_id": sid,
                    "workspace_id": wid,
                },
            )
            assert resp.status_code == 200
            assert "sk-another-secret" not in resp.text
    finally:
        api_mod._kernel = None


def test_stream_redacts_api_key_in_error(client: TestClient, ws_session: tuple[str, str]) -> None:
    """Error event should not contain raw api_key values."""
    api_mod = _get_api_mod()
    if api_mod:
        api_mod._kernel = None
    wid, sid = ws_session

    policy = PolicyEngine(
        rules=[
            PolicyRule("*", "call_model", "*", DecisionType.deny),
        ]
    )
    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(shared_db, policy_engine=policy)
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post(
                "/chat/stream",
                json={
                    "text": "api_key=sk-test-secret-in-error",
                    "session_id": sid,
                    "workspace_id": wid,
                },
            )
            assert resp.status_code == 200
            assert "sk-test-secret-in-error" not in resp.text
    finally:
        api_mod._kernel = None


def test_stream_error_event_no_traceback(client: TestClient, ws_session: tuple[str, str]) -> None:
    """Error event should not expose Python traceback."""
    api_mod = _get_api_mod()
    if api_mod:
        api_mod._kernel = None
    wid, sid = ws_session

    adapter = MockModel(response_text="", fail_on_prompt="crash")
    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(shared_db, model_adapter=adapter)
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post(
                "/chat/stream",
                json={
                    "text": "crash",
                    "session_id": sid,
                    "workspace_id": wid,
                },
            )
            assert resp.status_code == 200
            assert "Traceback" not in resp.text
            assert 'File "' not in resp.text
    finally:
        api_mod._kernel = None


def test_stream_approval_summary_redacted(client: TestClient, ws_session: tuple[str, str]) -> None:
    """Approval required event should have redacted summary."""
    api_mod = _get_api_mod()
    if api_mod:
        api_mod._kernel = None
    wid, sid = ws_session

    cap_reg = CapabilityRegistry()
    cap_reg.register(
        "write_file",
        CapabilityManifest(
            name="write_file",
            version="1.0",
            type=CapabilityType.tool,
            description="Test",
            input_schema={},
            output_schema={},
            permissions=[Permission(resource="*", operations=["execute"])],
            risk_level=RiskLevel.low,
            allowed_contexts=["interactive", "background"],
            approval_required=True,
            audit_required=True,
            idempotent=True,
        ),
        lambda **kw: ToolResult(status="ok", summary="done"),
    )

    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="using tool with api_key=my-secret-key",
        tool_intents=[{"name": "write_file", "arguments": {}}],
    )
    shared_db = getattr(api_mod, "_db") if getattr(api_mod, "_db") else api_mod.get_db()
    kernel = RuntimeKernel(shared_db, capability_registry=cap_reg, model_adapter=mock_adapter)
    api_mod._kernel = kernel

    try:
        with patch.dict("os.environ", {}, clear=True):
            c = TestClient(app)
            resp = c.post(
                "/chat/stream",
                json={
                    "text": "write file with secret key",
                    "session_id": sid,
                    "workspace_id": wid,
                },
            )
            assert resp.status_code == 200
            assert "my-secret-key" not in resp.text
    finally:
        api_mod._kernel = None
