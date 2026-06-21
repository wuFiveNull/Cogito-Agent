from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestWorkspaceFilesPage:
    def test_list_page_returns_200(self) -> None:
        resp = client.get("/console/workspace/files")
        assert resp.status_code == 200
        assert "Workspace Files" in resp.text

    def test_scan_action(self) -> None:
        resp = client.post("/console/workspace/files/scan", data={})
        assert resp.status_code in (200, 303)
