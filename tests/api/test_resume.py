from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _setup(client: TestClient) -> tuple[str, str]:
    ws = client.post("/sessions", json={"workspace_id": "ws-r", "title": "Test"}).json()
    return ws["workspace_id"], ws["id"]


def test_resume_nonexistent_approval(client: TestClient) -> None:
    ws_id, sess_id = _setup(client)
    resp = client.post("/chat/resume", json={
        "approval_id": "nonexistent",
        "session_id": sess_id,
        "workspace_id": ws_id,
        "decision": "approved",
    })
    assert resp.status_code == 404


def test_resume_already_resolved(client: TestClient) -> None:
    ws_id, sess_id = _setup(client)
    # Create a pending approval first
    create = client.post("/approvals", params={
        "workspace_id": ws_id, "actor_id": "user",
        "capability_name": "test.tool", "operation": "run",
    })
    assert create.status_code == 200
    aid = create.json()["id"]

    # Resolve it first via the normal approval endpoint
    resolve = client.post(f"/approvals/{aid}/resolve", json={"decision": "allow"})
    assert resolve.status_code == 200

    # Attempting to resume with the same approval should fail (already resolved)
    resp = client.post("/chat/resume", json={
        "approval_id": aid,
        "session_id": sess_id,
        "workspace_id": ws_id,
        "decision": "approved",
    })
    assert resp.status_code == 404


def test_resume_without_session(client: TestClient) -> None:
    resp = client.post("/chat/resume", json={
        "approval_id": "some-id",
        "session_id": "nonexistent",
        "workspace_id": "ws-r",
        "decision": "approved",
    })
    assert resp.status_code == 404
