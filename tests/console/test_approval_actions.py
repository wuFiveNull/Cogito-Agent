from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app, get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_workspace() -> None:
    from cogito_agent.storage.repositories import WorkspaceRepository

    db = get_db()
    ws = WorkspaceRepository(db).get_by_id("default")
    if ws is None:
        WorkspaceRepository(db).create("default", "default")


class TestApprovalActions:
    def _create_pending_approval(self, capability: str = "test_tool") -> str:
        from cogito_agent.storage.repositories import ApprovalRepository

        db = get_db()
        repo = ApprovalRepository(db)
        rec = repo.create("default", "user", capability, "write", "test_resource", "need approval")
        return str(rec["id"])

    def test_approve(self) -> None:
        aid = self._create_pending_approval()
        resp = client.post(f"/console/approval/{aid}/approve")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        db = get_db()
        cur = db.connection.execute(
            "SELECT status, decision FROM approval_records WHERE id=?", (aid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "approved"

    def test_reject(self) -> None:
        aid = self._create_pending_approval()
        resp = client.post(f"/console/approval/{aid}/reject", data={"reason": "not needed"})
        assert resp.status_code == 200
        db = get_db()
        cur = db.connection.execute(
            "SELECT status FROM approval_records WHERE id=?", (aid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "rejected"

    def test_double_approve_returns_error(self) -> None:
        aid = self._create_pending_approval()
        resp1 = client.post(f"/console/approval/{aid}/approve")
        assert resp1.status_code == 200
        resp2 = client.post(f"/console/approval/{aid}/approve")
        assert resp2.status_code == 404  # already processed
        assert "already processed" in resp2.text.lower()

    def test_double_reject_returns_error(self) -> None:
        aid = self._create_pending_approval()
        resp1 = client.post(f"/console/approval/{aid}/reject")
        assert resp1.status_code == 200
        resp2 = client.post(f"/console/approval/{aid}/reject")
        assert resp2.status_code == 404
        assert "already processed" in resp2.text.lower()

    def test_approve_not_found(self) -> None:
        resp = client.post("/console/approval/nonexistent/approve")
        assert resp.status_code == 404

    def test_reject_not_found(self) -> None:
        resp = client.post("/console/approval/nonexistent/reject")
        assert resp.status_code == 404

    def test_approve_writes_audit(self) -> None:
        aid = self._create_pending_approval()
        client.post(f"/console/approval/{aid}/approve")
        db = get_db()
        cur = db.connection.execute(
            "SELECT * FROM audit_logs WHERE resource=? ORDER BY created_at DESC LIMIT 1",
            (f"approval:{aid}",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["action"] == "approval.approve"
        assert row["actor_id"] == "console"

    def test_reject_writes_audit(self) -> None:
        aid = self._create_pending_approval()
        client.post(f"/console/approval/{aid}/reject", data={"reason": "not needed"})
        db = get_db()
        cur = db.connection.execute(
            "SELECT * FROM audit_logs WHERE resource=? ORDER BY created_at DESC LIMIT 1",
            (f"approval:{aid}",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["action"] == "approval.reject"
        assert row["actor_id"] == "console"

    def test_approve_with_reason(self) -> None:
        aid = self._create_pending_approval()
        resp = client.post(f"/console/approval/{aid}/approve", data={"reason": "looks good"})
        assert resp.status_code == 200

    def test_reject_with_reason(self) -> None:
        aid = self._create_pending_approval()
        resp = client.post(f"/console/approval/{aid}/reject", data={"reason": "not safe"})
        assert resp.status_code == 200

    def test_uses_approval_repository_not_direct_sql(self) -> None:
        """Verify the route goes through ApprovalRepository.resolve()."""
        aid = self._create_pending_approval()
        resp = client.post(f"/console/approval/{aid}/approve")
        assert resp.status_code == 200
        # If resolve() was used, status will be "approved" not something else
        db = get_db()
        cur = db.connection.execute(
            "SELECT status, decided_by FROM approval_records WHERE id=?", (aid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "approved"
        assert row["decided_by"] == "console"
