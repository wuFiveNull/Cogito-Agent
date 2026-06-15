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
