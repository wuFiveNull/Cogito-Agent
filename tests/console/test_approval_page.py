from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestApprovalPage:
    def test_approval_page_returns_200(self) -> None:
        resp = client.get("/console/approval")
        assert resp.status_code == 200

    def test_approval_page_contains_stats(self) -> None:
        resp = client.get("/console/approval")
        html = resp.text
        assert "Total" in html
        assert "Pending" in html
        assert "Approved" in html
        assert "Rejected" in html

    def test_approval_page_empty_db_no_crash(self) -> None:
        resp = client.get("/console/approval")
        assert resp.status_code == 200

    def test_approval_page_status_filter(self) -> None:
        resp = client.get("/console/approval?status=pending")
        assert resp.status_code == 200

    def test_approval_page_status_filter_approved(self) -> None:
        resp = client.get("/console/approval?status=approved")
        assert resp.status_code == 200

    def test_approval_page_status_filter_rejected(self) -> None:
        resp = client.get("/console/approval?status=rejected")
        assert resp.status_code == 200

    def test_approval_page_search(self) -> None:
        resp = client.get("/console/approval?q=test")
        assert resp.status_code == 200

    def test_approval_page_missing_risk_filter_no_crash(self) -> None:
        """Risk filter column does not exist in schema; graceful fallback."""
        resp = client.get("/console/approval?risk=high")
        assert resp.status_code == 200


class TestApprovalDetail:
    def test_detail_not_found(self) -> None:
        resp = client.get("/console/approval/nonexistent-approval-id")
        assert resp.status_code == 404

    def test_detail_returns_200_for_valid(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.storage.repositories import ApprovalRepository

        db = get_db()
        repo = ApprovalRepository(db)
        rec = repo.create("default", "user", "test_tool", "write", "test_resource", "test reason")
        aid = str(rec["id"])

        resp = client.get(f"/console/approval/{aid}")
        assert resp.status_code == 200
        assert "test_tool" in resp.text or "test" in resp.text


@pytest.fixture(autouse=True)
def _ensure_workspace() -> None:
    from cogito_agent.api.app import get_db
    from cogito_agent.storage.repositories import WorkspaceRepository

    db = get_db()
    ws = WorkspaceRepository(db).get_by_id("default")
    if ws is None:
        WorkspaceRepository(db).create("default", "default")
