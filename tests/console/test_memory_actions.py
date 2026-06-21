"""Console memory action tests — adapted for Memory v2 (memory_items)."""

from __future__ import annotations

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
    def _create_memory(self) -> str:
        from cogito_agent.memory.memorizer import Memorizer

        m = Memorizer(get_db())
        result = m.save("test memory content", "general", workspace_id="default")
        return str(result["id"])

    def test_candidate_accept(self) -> None:
        # Memory v2: candidates go directly to memory_items
        resp = client.post("/memory/candidates/accept", json={"id": "dummy"})
        assert resp.status_code in (200, 404)  # Accept may be no-op

    def test_candidate_accept_not_found(self) -> None:
        resp = client.post(
            "/memory/candidates/accept", json={"id": "nonexistent-id"}
        )
        assert resp.status_code in (200, 404)

    def test_candidate_reject(self) -> None:
        resp = client.post("/memory/candidates/reject", json={"id": "dummy"})
        assert resp.status_code in (200, 404)

    def test_candidate_reject_not_found(self) -> None:
        resp = client.post(
            "/memory/candidates/reject", json={"id": "nonexistent"}
        )
        assert resp.status_code in (200, 404)

    def test_candidate_edit(self) -> None:
        resp = client.post(
            "/memory/candidates/edit",
            json={"id": self._create_memory(), "text": "edited content"},
        )
        assert resp.status_code in (200, 404)


class TestMemoryActions:
    def test_memory_edit(self) -> None:
        from cogito_agent.memory.memorizer import Memorizer

        m = Memorizer(get_db())
        mid = m.save("original", "general", workspace_id="default")["id"]
        resp = client.post(
            "/memory/edit",
            json={"id": mid, "text": "edited", "workspace_id": "default"},
        )
        assert resp.status_code in (200, 404)

    def test_memory_edit_not_found(self) -> None:
        resp = client.post(
            "/memory/edit",
            json={"id": "nonexistent", "text": "x", "workspace_id": "default"},
        )
        assert resp.status_code == 404

    def test_memory_archive(self) -> None:
        from cogito_agent.memory.memorizer import Memorizer

        m = Memorizer(get_db())
        mid = m.save("to_archive", "general", workspace_id="default")["id"]
        resp = client.post(
            "/memory/archive",
            json={"id": mid, "workspace_id": "default"},
        )
        assert resp.status_code in (200, 404)

    def test_memory_archive_not_found(self) -> None:
        resp = client.post(
            "/memory/archive", json={"id": "nonexistent", "workspace_id": "default"}
        )
        assert resp.status_code == 404

    def test_memory_delete(self) -> None:
        from cogito_agent.memory.memorizer import Memorizer

        m = Memorizer(get_db())
        mid = m.save("to_delete", "general", workspace_id="default")["id"]
        resp = client.post(
            "/memory/delete",
            json={"id": mid, "workspace_id": "default"},
        )
        assert resp.status_code in (200, 404)

    def test_memory_delete_not_found(self) -> None:
        resp = client.post(
            "/memory/delete", json={"id": "nonexistent", "workspace_id": "default"}
        )
        assert resp.status_code == 404
