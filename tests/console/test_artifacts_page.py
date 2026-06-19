from __future__ import annotations

from fastapi.testclient import TestClient
from cogito_agent.api.app import app

client = TestClient(app)


class TestArtifactsPage:
    def test_list_page_returns_200(self) -> None:
        resp = client.get("/console/artifacts")
        assert resp.status_code == 200
        assert "Artifacts" in resp.text

    def test_detail_not_found(self) -> None:
        resp = client.get("/console/artifacts/nonexistent")
        assert resp.status_code == 404

    def test_download_not_found(self) -> None:
        resp = client.get("/console/artifacts/nonexistent/download")
        assert resp.status_code == 404
