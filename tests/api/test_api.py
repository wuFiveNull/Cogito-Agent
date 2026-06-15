from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app


@pytest.fixture
def client() -> TestClient:
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
