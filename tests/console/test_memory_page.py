from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestMemoryPage:
    def test_memory_page_returns_200(self) -> None:
        resp = client.get("/console/memory")
        assert resp.status_code == 200

    def test_memory_page_contains_stats(self) -> None:
        resp = client.get("/console/memory")
        html = resp.text
        assert "Total" in html
        assert "Pending" in html
        assert "Active" in html

    def test_memory_page_has_filters(self) -> None:
        resp = client.get("/console/memory")
        html = resp.text
        assert "Filter" in html or "filter" in html.lower()
        assert "Clear" in html or "clear" in html.lower()

    def test_memory_page_tabs(self) -> None:
        resp = client.get("/console/memory")
        html = resp.text
        assert "All" in html
        assert "Candidates" in html
        assert "Memories" in html

    def test_memory_page_tab_candidates(self) -> None:
        resp = client.get("/console/memory?tab=candidates")
        assert resp.status_code == 200

    def test_memory_page_tab_memories(self) -> None:
        resp = client.get("/console/memory?tab=memories")
        assert resp.status_code == 200

    def test_memory_page_status_filter(self) -> None:
        resp = client.get("/console/memory?status=pending")
        assert resp.status_code == 200

    def test_memory_page_search(self) -> None:
        resp = client.get("/console/memory?q=hello")
        assert resp.status_code == 200

    def test_memory_page_empty_db_no_crash(self) -> None:
        resp = client.get("/console/memory")
        assert resp.status_code == 200


class TestMemoryDetail:
    def test_memory_detail_not_found(self) -> None:
        resp = client.get("/console/memory/nonexistent-id-12345")
        assert resp.status_code == 404

    def test_memory_detail_returns_200_for_valid(self) -> None:
        import uuid
        from cogito_agent.api.app import get_db
        from cogito_agent.storage.repositories import WorkspaceRepository, MemoryRepository

        db = get_db()
        ws = WorkspaceRepository(db).get_by_id("default")
        if ws is None:
            WorkspaceRepository(db).create("default", "default")
        mid = str(uuid.uuid4())
        repo = MemoryRepository(db)
        repo.create(mid, "default", "test content for detail page", "test")

        resp = client.get(f"/console/memory/{mid}")
        assert resp.status_code == 200
        assert "test content for detail page" in resp.text or "test content" in resp.text
