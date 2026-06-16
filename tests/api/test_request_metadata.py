from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app


def test_x_request_id_propagated_to_response() -> None:
    client = TestClient(app)
    custom_id = "custom-request-id-001"
    resp = client.get("/workspaces", headers={"X-Request-ID": custom_id})
    assert resp.headers.get("X-Request-ID") == custom_id


def test_x_request_id_generated_if_missing() -> None:
    client = TestClient(app)
    resp = client.get("/workspaces")
    rid = resp.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) > 0


def test_request_id_appears_in_error_response() -> None:
    client = TestClient(app)
    custom_id = "error-req-id-999"
    resp = client.get("/workspaces/nonexistent", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 404
    data = resp.json()
    assert "request_id" in data["error"]
    assert isinstance(data["error"]["request_id"], str)
    assert resp.headers.get("X-Request-ID") == custom_id


def test_request_id_x_header_on_success_and_error() -> None:
    client = TestClient(app)
    custom_id = "multi-req-id-555"
    resp_ok = client.get("/workspaces", headers={"X-Request-ID": custom_id})
    assert resp_ok.status_code in (200, 500)
    assert resp_ok.headers.get("X-Request-ID") == custom_id

    resp_err = client.get("/workspaces/nonexistent", headers={"X-Request-ID": custom_id})
    assert resp_err.status_code == 404
    assert resp_err.headers.get("X-Request-ID") == custom_id
