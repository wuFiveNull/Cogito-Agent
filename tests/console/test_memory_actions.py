from __future__ import annotations

import uuid

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


class TestCandidateActions:
    def _create_pending_candidate(self) -> str:
        from cogito_agent.storage.repositories import MemoryCandidateRepository

        db = get_db()
        repo = MemoryCandidateRepository(db)
        cand = repo.create("default", "candidate test text", "general", "test reason", 0.8)
        return str(cand["id"])

    def test_candidate_accept(self) -> None:
        cid = self._create_pending_candidate()
        resp = client.post(f"/console/memory/candidates/{cid}/accept")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_candidate_accept_not_found(self) -> None:
        resp = client.post("/console/memory/candidates/nonexistent-cand/accept")
        assert resp.status_code == 404

    def test_candidate_reject(self) -> None:
        cid = self._create_pending_candidate()
        resp = client.post(f"/console/memory/candidates/{cid}/reject")
        assert resp.status_code == 200

    def test_candidate_reject_not_found(self) -> None:
        resp = client.post("/console/memory/candidates/nonexistent-cand/reject")
        assert resp.status_code == 404

    def test_candidate_edit(self) -> None:
        cid = self._create_pending_candidate()
        resp = client.post(
            f"/console/memory/candidates/{cid}/edit",
            data={"text": "updated text", "type": "preference", "confidence": 0.9},
        )
        assert resp.status_code == 200
        db = get_db()
        cur = db.connection.execute(
            "SELECT text FROM memory_candidates WHERE id=?", (cid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["text"] == "updated text"

    def test_candidate_edit_not_found(self) -> None:
        resp = client.post(
            "/console/memory/candidates/nonexistent/edit",
            data={"text": "x", "type": "general", "confidence": 0.5},
        )
        assert resp.status_code == 404


class TestMemoryActions:
    def _create_memory(self, text: str = "memory text") -> str:
        from cogito_agent.storage.repositories import MemoryRepository, WorkspaceRepository

        db = get_db()
        ws = WorkspaceRepository(db).get_by_id("default")
        if ws is None:
            WorkspaceRepository(db).create("default", "default")
        mid = str(uuid.uuid4())
        repo = MemoryRepository(db)
        repo.create(mid, "default", text, "general")
        return mid

    def test_memory_edit(self) -> None:
        mid = self._create_memory()
        resp = client.post(
            f"/console/memory/{mid}/edit",
            data={"text": "edited memory text"},
        )
        assert resp.status_code == 200
        db = get_db()
        cur = db.connection.execute(
            "SELECT text FROM memories WHERE id=?", (mid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["text"] == "edited memory text"

    def test_memory_edit_not_found(self) -> None:
        resp = client.post(
            "/console/memory/nonexistent-mem/edit",
            data={"text": "x"},
        )
        assert resp.status_code == 404

    def test_memory_archive(self) -> None:
        mid = self._create_memory()
        resp = client.post(f"/console/memory/{mid}/archive")
        assert resp.status_code == 200
        db = get_db()
        cur = db.connection.execute(
            "SELECT archived_at FROM memories WHERE id=?", (mid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["archived_at"] is not None

    def test_memory_archive_not_found(self) -> None:
        resp = client.post("/console/memory/nonexistent-mem/archive")
        assert resp.status_code == 404

    def test_memory_delete(self) -> None:
        mid = self._create_memory()
        resp = client.post(f"/console/memory/{mid}/delete")
        assert resp.status_code == 200
        db = get_db()
        cur = db.connection.execute(
            "SELECT deleted_at FROM memories WHERE id=?", (mid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row["deleted_at"] is not None

    def test_memory_delete_not_found(self) -> None:
        resp = client.post("/console/memory/nonexistent-mem/delete")
        assert resp.status_code == 404
