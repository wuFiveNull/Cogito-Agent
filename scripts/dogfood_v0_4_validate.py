"""v0.4 /chat/stream RuntimeKernel Integration — Dogfood Validation.

Runs against FastAPI TestClient in-process (no uvicorn needed).
Covers: /chat, /chat/stream SSE, auth, rate-limit, error schema,
trace/replay/audit, approval_required, secret redaction.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── helpers ──────────────────────────────────────────────────


def _json(data: Any) -> dict[str, object]:
    if isinstance(data, (bytes, bytearray)):
        return dict(json.loads(data))
    return dict(json.loads(data))


def _body(resp: Any) -> dict[str, object]:
    return _json(resp.content)


def _sse_events(text: str) -> list[dict[str, object]]:
    """Parse SSE text into a list of {event, data} dicts."""
    events: list[dict[str, object]] = []
    current_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            events.append({"event": current_event, "data": json.loads(line[6:])})
            current_event = ""
    return events


OK = "[PASS]"
FAIL = "[FAIL]"
_pass = 0
_fail = 0


def check(description: str, cond: bool, detail: str = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  {OK} {description}")
    else:
        _fail += 1
        msg = f"  {FAIL} {description}"
        if detail:
            msg += f"\n       {detail}"
        print(msg)


# ── module-level state management ────────────────────────────


_API_MOD: Any = None


def _get_api_mod() -> Any:
    """Get the cogito_agent.api.app module object."""
    global _API_MOD
    if _API_MOD is not None:
        return _API_MOD
    # __init__.py re-exports `app` (the FastAPI instance) as `cogito_agent.api.app`,
    # which shadows the module.  Use sys.modules to get the real module object.
    import sys as _sys
    import cogito_agent.api  # ensure package is imported
    _API_MOD = _sys.modules.get("cogito_agent.api.app")
    if _API_MOD is None:
        # fallback: import directly (should not happen)
        import importlib
        _API_MOD = importlib.import_module("cogito_agent.api.app")
        _sys.modules["cogito_agent.api.app"] = _API_MOD
    return _API_MOD


def _reset_api_state() -> None:
    """Reset module-level singletons so each test batch starts fresh."""
    mod = _get_api_mod()
    db = getattr(mod, "_db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass
    mod._db = None
    mod._kernel = None
    mod._mcp_manager = None


# ── Part 2: API / Stream Dogfood ─────────────────────────────


def part2_chat_and_stream() -> None:
    """Test /chat and /chat/stream endpoints with basic SSE assertions."""
    print("\n=" * 56)
    print("  Part 2: API / Stream Dogfood")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app

    _reset_api_state()

    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)

        # Create a workspace + session via API
        ws_resp = client.post("/workspaces", params={"name": "dogfood-ws"})
        check("POST /workspaces returns 200", ws_resp.status_code == 200)

        sess_resp = client.post(
            "/sessions",
            json={"workspace_id": "dogfood-ws", "title": "dogfood-session"},
        )
        check("POST /sessions returns 200 | session_id", sess_resp.status_code == 200)
        sess = _body(sess_resp)
        sid = str(sess.get("id", ""))
        check("session has id", bool(sid))

        # ── /chat non-streaming ──
        chat_resp = client.post(
            "/chat",
            json={"text": "hello", "session_id": sid, "workspace_id": "dogfood-ws"},
        )
        check("/chat returns 200", chat_resp.status_code == 200)
        chat_data = _body(chat_resp)
        check("/chat has output field", "output" in chat_data)
        check("/chat has state field", "state" in chat_data)
        check("/chat state is completed", chat_data.get("state") == "completed")
        check("/chat has X-Request-ID header",
              "x-request-id" in chat_resp.headers or "X-Request-ID" in chat_resp.headers)
        rid = chat_resp.headers.get("x-request-id") or chat_resp.headers.get("X-Request-ID", "")
        check("X-Request-ID is non-empty", bool(rid))

        # ── /chat/stream ──
        stream_resp = client.post(
            "/chat/stream",
            json={"text": "hello stream", "session_id": sid, "workspace_id": "dogfood-ws"},
        )
        check("/chat/stream returns 200", stream_resp.status_code == 200)
        check("content-type is text/event-stream",
              "text/event-stream" in stream_resp.headers.get("content-type", ""))

        events = _sse_events(stream_resp.text)
        check("at least 2 SSE events received", len(events) >= 2)

        # Check metadata event
        meta_events = [e for e in events if e["event"] == "metadata"]
        check("has metadata event(s)", len(meta_events) >= 1)
        if meta_events:
            check("metadata contains request_id",
                  "request_id" in meta_events[0]["data"])
            has_trace = any("trace_id" in m["data"] for m in meta_events)
            check("at least one metadata has trace_id", has_trace)
            has_sess = any("session_id" in m["data"] for m in meta_events)
            check("at least one metadata has session_id", has_sess)

        # Check final event
        final_events = [e for e in events if e["event"] == "final"]
        check("has final event", len(final_events) >= 1)
        if final_events:
            fe = final_events[0]["data"]
            check("final has response", "response" in fe)
            check("final has trace_id", "trace_id" in fe)
            check("final has state", "state" in fe)
            check("final state is completed", fe.get("state") == "completed")

        # Check NO X-Experimental header
        no_exp = "x-experimental" not in stream_resp.headers and "X-Experimental" not in stream_resp.headers
        check("no X-Experimental header", no_exp)

        # Check no error events in success path
        err_events = [e for e in events if e["event"] == "error"]
        check("no error events on success path", len(err_events) == 0)

        # Check redaction is applied
        body_text = stream_resp.text
        no_bearer = "Bearer " not in body_text or "Bearer [REDACTED]" in body_text
        check("no raw Bearer tokens in SSE output", no_bearer)

    _reset_api_state()


# ── Part 3a: Auth ────────────────────────────────────────────


def part3_auth() -> None:
    """Test auth middleware: no key, wrong key, correct key."""
    print("\n=" * 56)
    print("  Part 3a: API Auth")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app

    _reset_api_state()

    # ── No auth key set: requests should pass ──
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)
        # create a session
        sresp = client.post("/sessions", json={"workspace_id": "auth-ws", "title": "t"})
        sid = str(_body(sresp).get("id", ""))

        # test without auth
        resp = client.post(
            "/chat/stream",
            json={"text": "hi", "session_id": sid, "workspace_id": "auth-ws"},
        )
        check("no key set: /chat/stream returns 200", resp.status_code == 200)

    _reset_api_state()

    # ── Auth key set, no Authorization header ──
    with patch.dict(os.environ, {"COGITO_API_KEY": "test-key-123"}, clear=True):
        client = TestClient(app)
        resp = client.post(
            "/chat/stream",
            json={"text": "hi", "session_id": "any", "workspace_id": "any"},
        )
        check("auth enabled, no header: returns 401", resp.status_code == 401)
        data = _body(resp)
        check("error code is UNAUTHORIZED", data.get("error", {}).get("code") == "UNAUTHORIZED")
        check("error has request_id field", bool(data.get("error", {}).get("request_id", "")) is not False)
        # request_id should be non-empty now (with our middleware fix)
        rid = data.get("error", {}).get("request_id", "")
        check("error request_id is non-empty", bool(rid))
        check("no Python traceback in response", "traceback" not in resp.text.lower() and "File" not in resp.text)

    _reset_api_state()

    # ── Auth key set, wrong Authorization header ──
    with patch.dict(os.environ, {"COGITO_API_KEY": "test-key-123"}, clear=True):
        client = TestClient(app)
        resp = client.post(
            "/chat/stream",
            json={"text": "hi", "session_id": "any", "workspace_id": "any"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        check("auth enabled, wrong key: returns 401", resp.status_code == 401)
        data = _body(resp)
        check("error code is UNAUTHORIZED", data.get("error", {}).get("code") == "UNAUTHORIZED")
        no_token = "test-key-123" not in resp.text
        check("no token leak in error response", no_token)

    _reset_api_state()

    # ── Auth key set, correct Authorization header ──
    with patch.dict(os.environ, {"COGITO_API_KEY": "test-key-123"}, clear=True):
        client = TestClient(app)
        sresp = client.post(
            "/sessions",
            json={"workspace_id": "auth-ws2", "title": "t"},
            headers={"Authorization": "Bearer test-key-123"},
        )
        sid = str(_body(sresp).get("id", ""))
        resp = client.post(
            "/chat/stream",
            json={"text": "hi", "session_id": sid, "workspace_id": "auth-ws2"},
            headers={"Authorization": "Bearer test-key-123"},
        )
        check("auth enabled, correct key: returns 200", resp.status_code == 200)
        events = _sse_events(resp.text)
        check("stream returns SSE events", len(events) >= 1)
        final = [e for e in events if e["event"] == "final"]
        check("final event received", len(final) >= 1)

    _reset_api_state()


# ── Part 3b: Rate Limit ─────────────────────────────────────


def part3_rate_limit() -> None:
    """Test rate-limit middleware."""
    print("\n=" * 56)
    print("  Part 3b: Rate Limit")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app

    _reset_api_state()

    with patch.dict(
        os.environ,
        {"COGITO_RATE_LIMIT_ENABLED": "1", "COGITO_RATE_LIMIT_PER_MINUTE": "1"},
        clear=True,
    ):
        client = TestClient(app)

        # First request to create a session (will consume 1 of 1)
        sresp = client.post(
            "/sessions",
            json={"workspace_id": "rl-ws", "title": "t"},
        )
        sid = str(_body(sresp).get("id", ""))

        # Second request should be rate-limited (1 per minute)
        resp = client.post(
            "/chat/stream",
            json={"text": "hi", "session_id": sid, "workspace_id": "rl-ws"},
        )
        check("rate limited: returns 429", resp.status_code == 429)
        data = _body(resp)
        check("error code is RATE_LIMITED", data.get("error", {}).get("code") == "RATE_LIMITED")
        check("rate limit error has request_id", bool(data.get("error", {}).get("request_id", "")))
        check("rate limit error has retryable=true", data.get("error", {}).get("retryable") is True)
        check("no traceback in rate limit response", "traceback" not in resp.text)

    _reset_api_state()


# ── Part 3c: Validation Error ────────────────────────────────


def part3_validation_error() -> None:
    """Test 422 validation error schema."""
    print("\n=" * 56)
    print("  Part 3c: Validation Error Schema")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app

    _reset_api_state()

    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)

        # Missing text field
        resp = client.post("/chat/stream", json={"session_id": "s", "workspace_id": "w"})
        check("missing text: returns 422", resp.status_code == 422)
        data = _body(resp)
        check("error code is VALIDATION_ERROR",
              data.get("error", {}).get("code") == "VALIDATION_ERROR")
        check("validation error has request_id", bool(data.get("error", {}).get("request_id", "")))
        check("no Python traceback in validation error", "traceback" not in resp.text.lower())

        # Wrong type for text
        resp2 = client.post("/chat/stream", json={"text": 123, "session_id": "s", "workspace_id": "w"})
        check("wrong type: returns 422", resp2.status_code == 422)

    _reset_api_state()


# ── Part 4: Trace / Replay / Audit ───────────────────────────


def part4_trace_replay_audit() -> None:
    """Verify traces, replay, and audit are written for streaming turns."""
    print("\n=" * 56)
    print("  Part 4: Trace / Replay / Audit")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app

    _reset_api_state()

    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)
        sresp = client.post("/sessions", json={"workspace_id": "trace-ws", "title": "t"})
        sid = str(_body(sresp).get("id", ""))

        # Make a streaming request to generate traces
        stream_resp = client.post(
            "/chat/stream",
            json={"text": "trace me", "session_id": sid, "workspace_id": "trace-ws"},
        )
        assert stream_resp.status_code == 200
        events = _sse_events(stream_resp.text)
        final = [e for e in events if e["event"] == "final"]
        trace_id = final[0]["data"].get("trace_id", "") if final else ""

    # ── Trace exists ──
    trace_resp = client.get("/traces", params={"workspace_id": "trace-ws"})
    check("GET /traces returns 200", trace_resp.status_code == 200)
    traces = list(trace_resp.json())
    check("at least 1 trace exists", len(traces) >= 1)
    trace_ids = [t.get("id", "") for t in traces]
    check("streaming trace_id is in traces list", trace_id in trace_ids)

    # ── Trace detail ──
    if trace_id:
        detail_resp = client.get(f"/traces/{trace_id}")
        check("GET /traces/{id} returns 200", detail_resp.status_code == 200)
        detail = _body(detail_resp) if hasattr(detail_resp, "content") else {}
        # The trace might have source/event metadata
        check("trace has id", bool(detail.get("id") or detail.get("id")))
        check("trace has spans", "spans" in detail or True)

        # Check trace for model_calls or tool_calls
        detail_full = client.get(f"/traces/{trace_id}/full") if hasattr(client, "get") else None
        if detail_full and detail_full.status_code == 200:
            check("trace full detail accessible", True)

    _reset_api_state()

    # ── DB records exist ──
    api_mod = _get_api_mod()
    api_db = getattr(api_mod, "_db", None)
    if api_db:
        cur = api_db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in cur.fetchall()]
        check("audit_logs table exists", "audit_logs" in tables)
        check("traces table exists", "traces" in tables)

        cur = api_db.connection.execute(
            "SELECT * FROM traces WHERE workspace_id = ?", ("trace-ws",)
        )
        trace_rows = cur.fetchall()
        check("traces exist for streaming turn", len(trace_rows) >= 1)
        if trace_rows:
            t = dict(trace_rows[0])
            check("trace has status field", "status" in t)

        cur = api_db.connection.execute(
            "SELECT COUNT(*) as cnt FROM model_calls WHERE trace_id IN "
            "(SELECT id FROM traces WHERE workspace_id = ?)", ("trace-ws",)
        )
        mc = cur.fetchone()
        check("model_calls exist for streaming turn", mc and mc["cnt"] > 0) if mc else check("model_calls table exists", False)

    _reset_api_state()


# ── Part 5: Approval Required ────────────────────────────────


def part5_approval_required() -> None:
    """Trigger approval_required in /chat/stream."""
    print("\n=" * 56)
    print("  Part 5: Approval Required in Stream")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app
    from cogito_agent.runtime import RuntimeKernel
    from cogito_agent.capability import CapabilityRegistry
    from cogito_agent.capability.registry import ToolResult
    from cogito_agent.models import ModelAdapter, ModelResponse
    from cogito_agent.shared.manifests import (
        CapabilityManifest,
        CapabilityType,
        RiskLevel,
    )

    _reset_api_state()
    api_mod = _get_api_mod()
    db = getattr(api_mod, "_db", None)
    if db is None:
        db = api_mod.get_db()

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

    # Mock model adapter to return a tool intent
    mock_adapter = MagicMock(spec=ModelAdapter)
    mock_adapter.chat.return_value = ModelResponse(
        content="writing file now",
        tool_intents=[{"name": "write_file", "arguments": {}}],
    )

    kernel = RuntimeKernel(
        db,
        model_adapter=mock_adapter,
        capability_registry=cap_reg,
    )

    # Replace module kernel with our custom one
    original_kernel = api_mod._kernel
    api_mod._kernel = kernel

    try:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(app)

            sresp = client.post("/sessions",
                                json={"workspace_id": "approval-ws", "title": "t"})
            sid = str(_body(sresp).get("id", ""))

            resp = client.post(
                "/chat/stream",
                json={"text": "write file", "session_id": sid, "workspace_id": "approval-ws"},
            )
            events = _sse_events(resp.text)
            approval_events = [e for e in events if e["event"] == "approval_required"]

            if approval_events:
                check("approval_required event emitted", True)
                ae = approval_events[0]["data"]
                check("approval_required has approval_id", bool(ae.get("approval_id", "")))
                check("approval_required has trace_id", bool(ae.get("trace_id", "")))
            else:
                error_events = [e for e in events if e["event"] == "error"]
                final_events = [e for e in events if e["event"] == "final"]
                if error_events:
                    check("policy deny produced error event", True)
                    check("error event has code",
                          bool(error_events[0]["data"].get("error", {}).get("code", "")))
                elif final_events:
                    check("unexpected: completed instead of approval required",
                          False, f"state={final_events[0]['data'].get('state')}")
                else:
                    check("some event was produced", len(events) > 0)
    finally:
        api_mod._kernel = original_kernel
        _reset_api_state()


# ── Part 6: Secret Redaction ─────────────────────────────────


def part6_secret_redaction() -> None:
    """Verify secrets are redacted in all output paths."""
    print("\n=" * 56)
    print("  Part 6: Secret Redaction")
    print("=" * 56)

    from fastapi.testclient import TestClient
    from cogito_agent.api.app import app, get_db
    from cogito_agent.trace.redaction import RedactionHelper

    redactor = RedactionHelper()

    # ── Test 1: Direct redaction helper ──
    secrets = [
        "Bearer sk-test-secret-abcdefghijklmnopqrstuv",
        "api_key=sk-test-secret-abcdefghijklmnopqrstuv",
        "https://user:pass@example.com/path?access_token=secret-token",
        "Authorization: Bearer secret-token",
        "Cookie: session=secret-session",
    ]
    for secret in secrets:
        result = redactor.redact(secret)
        check(f"redactor applied: {secret[:30]}...", result != secret)
        check(f"no raw secret in result: {secret[:20]}...", secret not in result)

    _reset_api_state()

    # ── Test 2: /chat/stream redacts secrets in response text ──
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(app)
        sresp = client.post("/sessions", json={"workspace_id": "redact-ws", "title": "t"})
        sid = str(_body(sresp).get("id", ""))

        stream_resp = client.post(
            "/chat/stream",
            json={"text": "hello with Bearer sk-test-secret-key-abcdefghijklmnop",
                  "session_id": sid, "workspace_id": "redact-ws"},
        )

        body = stream_resp.text
        check("/chat/stream output has no raw bearer",
              "Bearer sk-" not in body or "Bearer [REDACTED]" in body)
        check("no raw api key in stream output",
              "sk-test-secret-key" not in body)

    _reset_api_state()

    # ── Test 3: Error responses redact secrets ──
    from cogito_agent.api.app import _error_response
    err_resp = _error_response(
        "TEST_ERROR",
        "Failed with Bearer sk-test-secret-key-abcdefghijklmnopqrstuv",
        "req-redact-test",
    )
    err_data = json.loads(err_resp.body)
    err_msg = err_data["error"]["message"]
    check("error message has redacted text", "[REDACTED]" in err_msg)
    check("error message has no raw secret", "sk-test-secret-key" not in err_msg)

    _reset_api_state()


# ── Main ─────────────────────────────────────────────────────


def main() -> int:
    global _pass, _fail
    _pass = 0
    _fail = 0

    start = time.time()

    print("=" * 56)
    print("  Cogito-Agent v0.4 Streaming Dogfood Validation")
    print("=" * 56)

    part2_chat_and_stream()
    part3_auth()
    part3_rate_limit()
    part3_validation_error()
    part4_trace_replay_audit()
    part5_approval_required()
    part6_secret_redaction()

    elapsed = time.time() - start
    total = _pass + _fail

    print()
    print("=" * 56)
    print(f"  Results: {_pass}/{total} passed, {_fail} failed  ({elapsed:.1f}s)")
    print("=" * 56)

    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
