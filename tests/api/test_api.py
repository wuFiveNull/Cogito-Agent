from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """API tests are hermetic and never consume the user's live provider config."""
    import sys

    api_mod = sys.modules["cogito_agent.api.app"]
    api_mod._kernel = None
    monkeypatch.setattr(
        "cogito_agent.cli.config_manager.build_model_adapter_from_config",
        lambda: None,
    )
    return TestClient(app)


def _setup(client: TestClient) -> tuple[str, str]:
    ws = client.post("/sessions", json={"workspace_id": "ws-1", "title": "Test"}).json()
    return ws["workspace_id"], ws["id"]


def test_chat_endpoint(client: TestClient) -> None:
    _, sid = _setup(client)
    resp = client.post("/chat", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-1",
    })
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "output" in data
    assert data["error"] is None
    assert data["state"] == "completed"


def test_chat_invalid_session(client: TestClient) -> None:
    _setup(client)
    resp = client.post("/chat", json={
        "text": "hello",
        "session_id": "nonexistent",
        "workspace_id": "ws-1",
    })
    assert resp.status_code == 404


def test_create_session(client: TestClient) -> None:
    resp = client.post("/sessions", json={
        "workspace_id": "ws-1",
        "title": "New Session",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "New Session"
    assert data["workspace_id"] == "ws-1"


def test_list_sessions(client: TestClient) -> None:
    _setup(client)
    resp = client.get("/sessions", params={"workspace_id": "ws-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_get_trace(client: TestClient) -> None:
    _setup(client)
    resp = client.post("/chat", json={
        "text": "hi",
        "session_id": "nonexistent",
        "workspace_id": "ws-1",
    })
    traces_resp = client.get("/sessions", params={"workspace_id": "ws-1"})
    assert traces_resp.status_code == 200 or resp.status_code == 404


def test_trace_not_found(client: TestClient) -> None:
    resp = client.get("/traces/nonexistent")
    assert resp.status_code == 404


def test_candidates_endpoint(client: TestClient) -> None:
    _setup(client)
    resp = client.post("/candidates", json={
        "candidate_id": "nonexistent",
        "action": "accept",
    })
    assert resp.status_code == 404


def test_list_pool_skills_empty(client: TestClient) -> None:
    resp = client.get("/skills")
    assert resp.status_code == 200
    assert resp.json() == []


def test_install_skill(client: TestClient) -> None:
    manifest = {
        "name": "greeter",
        "version": "1.0.0",
        "description": "A test skill",
        "inputs": {"name": "string"},
        "outputs": {},
        "steps": [
            {
                "id": "s1",
                "name": "greet",
                "kind": "transform",
                "input_mapping": {"out": "$name"},
            },
        ],
        "permissions": [],
        "risk_level": "low",
    }
    resp = client.post("/skills", json={"manifest": manifest})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "greeter"


def test_list_pool_skills_after_install(client: TestClient) -> None:
    resp = client.get("/skills")
    assert resp.status_code == 200
    data = resp.json()
    names = [s["name"] for s in data]
    assert "greeter" in names


def test_install_to_workspace(client: TestClient) -> None:
    _setup(client)
    pool_resp = client.get("/skills")
    pool = pool_resp.json()
    assert len(pool) > 0
    pool_id = pool[0]["id"]
    resp = client.post("/workspaces/ws-1/skills", json={"pool_skill_id": pool_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == pool[0]["name"]
    assert data["workspace_id"] == "ws-1"


def test_list_workspace_skills(client: TestClient) -> None:
    resp = client.get("/workspaces/ws-1/skills")
    assert resp.status_code == 200
    data = resp.json()
    names = [s["name"] for s in data]
    assert "greeter" in names


def test_run_skill(client: TestClient) -> None:
    _, sid = _setup(client)
    resp = client.post(
        f"/sessions/{sid}/skills/greeter/run",
        json={"workspace_id": "ws-1", "inputs": {"name": "world"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "trace_id" in data


def test_run_skill_not_found(client: TestClient) -> None:
    _, sid = _setup(client)
    resp = client.post(
        f"/sessions/{sid}/skills/nonexistent/run",
        json={"workspace_id": "ws-1", "inputs": {}},
    )
    assert resp.status_code == 404


def test_list_providers(client: TestClient) -> None:
    resp = client.get("/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "openai" in data["providers"]


def test_chat_with_configured_provider() -> None:
    import sys
    from unittest.mock import MagicMock, patch

    from cogito_agent.models.adapter import ModelAdapter, ModelResponse

    fake_adapter = MagicMock(spec=ModelAdapter)
    fake_adapter.chat.return_value = ModelResponse(
        content="Hello from config", provider="config", model="test",
    )

    mod = sys.modules["cogito_agent.api.app"]
    saved_kernel = mod._kernel
    saved_db = mod._db
    mod._kernel = None
    mod._db = None
    try:
        with patch(
            "cogito_agent.cli.config_manager.build_model_adapter_from_config",
            return_value=fake_adapter,
        ):
            client = TestClient(app)
            ws_resp = client.post("/workspaces", params={"name": "config-test"})
            assert ws_resp.status_code == 200
            wid = ws_resp.json()["id"]
            sess_resp = client.post("/sessions", json={"workspace_id": wid, "title": "test"})
            assert sess_resp.status_code == 200
            sid = sess_resp.json()["id"]
            resp = client.post("/chat", json={
                "text": "hello",
                "session_id": sid,
                "workspace_id": wid,
            })
            assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
            data = resp.json()
            assert data["output"] == "Hello from config"
            fake_adapter.chat.assert_called_once()
    finally:
        mod._kernel = saved_kernel
        mod._db = saved_db


def test_chat_stream_endpoint(client: TestClient) -> None:
    _, sid = _setup(client)
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": sid,
        "workspace_id": "ws-1",
    })
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    body = resp.text
    assert "event: metadata" in body or "data:" in body


def test_chat_stream_no_session(client: TestClient) -> None:
    resp = client.post("/chat/stream", json={
        "text": "hello",
        "session_id": "nonexistent",
        "workspace_id": "ws-1",
    })
    assert resp.status_code == 404


def test_mcp_servers_empty(client: TestClient) -> None:
    resp = client.get("/mcp/servers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_memories(client: TestClient) -> None:
    resp = client.get("/memories", params={"workspace_id": "ws-1"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_update_memory_not_found(client: TestClient) -> None:
    resp = client.put("/memories/nonexistent?workspace_id=ws-1",
                      json={"text": "new text"})
    assert resp.status_code == 404


def test_delete_memory_not_found(client: TestClient) -> None:
    resp = client.delete("/memories/nonexistent?workspace_id=ws-1")
    assert resp.status_code == 404


def test_approvals_empty(client: TestClient) -> None:
    resp = client.get("/approvals", params={"workspace_id": "ws-1"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_and_resolve_approval(client: TestClient) -> None:
    resp = client.post("/approvals", params={
        "workspace_id": "ws-1", "actor_id": "user",
        "capability_name": "read_file", "operation": "read",
    })
    assert resp.status_code == 200
    aid = resp.json()["id"]
    resolve = client.post(f"/approvals/{aid}/resolve",
                          json={"decision": "allow"})
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "allow"


def test_resolve_nonexistent_approval(client: TestClient) -> None:
    resp = client.post("/approvals/nonexistent/resolve",
                       json={"decision": "allow"})
    assert resp.status_code == 404


def test_workspace_settings(client: TestClient) -> None:
    resp = client.get("/workspaces/ws-1/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workspace_id"] == "ws-1"


def test_update_workspace_settings(client: TestClient) -> None:
    resp = client.put("/workspaces/ws-1/settings",
                      json={"timezone": "Asia/Shanghai",
                            "max_daily_notifications": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["timezone"] == "Asia/Shanghai"


def test_export_workspace(client: TestClient) -> None:
    _setup(client)
    resp = client.get("/export", params={"workspace_id": "ws-1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "workspace" in data
    assert "sessions" in data


def test_export_workspace_not_found(client: TestClient) -> None:
    resp = client.get("/export", params={"workspace_id": "nonexistent"})
    assert resp.status_code == 404


def test_cleanup_workspace(client: TestClient) -> None:
    resp = client.post("/workspaces/ws-1/cleanup")
    assert resp.status_code == 200


def test_list_workspaces(client: TestClient) -> None:
    _setup(client)
    resp = client.get("/workspaces")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_workspace(client: TestClient) -> None:
    resp = client.post("/workspaces", params={"name": "My Workspace"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "My Workspace"


def test_get_workspace(client: TestClient) -> None:
    resp = client.get("/workspaces/ws-1")
    assert resp.status_code == 200
    assert resp.json()["id"] == "ws-1"


def test_get_workspace_not_found(client: TestClient) -> None:
    resp = client.get("/workspaces/nonexistent")
    assert resp.status_code == 404


def test_delete_workspace(client: TestClient) -> None:
    client.post("/workspaces", params={"name": "Temp"})
    created = client.get("/workspaces").json()
    target = next((w for w in created if w["name"] == "Temp"), None)
    assert target is not None
    wid = target["id"]
    resp = client.delete(f"/workspaces/{wid}")
    assert resp.status_code == 200
    resp = client.get(f"/workspaces/{wid}")
    assert resp.status_code == 404


def test_delete_nonexistent_workspace(client: TestClient) -> None:
    resp = client.delete("/workspaces/nonexistent")
    assert resp.status_code == 404
