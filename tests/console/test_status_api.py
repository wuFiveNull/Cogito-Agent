from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestStatusAPI:
    def test_status_returns_200(self) -> None:
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "db" in data
        assert "model" in data
        assert "secrets" in data
        assert "counts" in data

    def test_status_version(self) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert data["version"] == "0.8.0-dev"

    def test_status_db_fields(self) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        db_info = data["db"]
        assert "ok" in db_info
        assert "path" in db_info
        assert "migration_version" in db_info

    def test_status_counts(self) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        counts = data["counts"]
        assert isinstance(counts["memories"], int)
        assert isinstance(counts["approvals_pending"], int)
        assert isinstance(counts["autonomy_decisions_24h"], int)
        assert isinstance(counts["audit_events_24h"], int)
        assert isinstance(counts["traces_24h"], int)

    def test_status_model_fields(self) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        model = data["model"]
        assert "provider" in model
        assert "streaming_enabled" in model
        assert "timeout_seconds" in model

    def test_status_secrets_fields(self) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        secrets = data["secrets"]
        assert "backend" in secrets
        assert "available" in secrets

    def test_status_limitations(self) -> None:
        resp = client.get("/api/v1/status")
        data = resp.json()
        assert isinstance(data["limitations"], list)
        assert len(data["limitations"]) > 0
