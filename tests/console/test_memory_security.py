from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestMemorySecurity:
    def test_no_stack_trace(self) -> None:
        resp = client.post("/console/memory/candidates/nonexistent/accept")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_error_no_api_key_leak(self) -> None:
        """Ensure error responses don't contain raw API keys."""
        resp = client.post("/console/memory/candidates/nonexistent/accept")
        html = resp.text
        assert "sk-" not in html.replace("[REDACTED", "")

    def test_memory_content_redacted(self) -> None:
        """Memory content containing secrets should be redacted."""
        import uuid

        from cogito_agent.api.app import get_db
        from cogito_agent.storage.repositories import MemoryRepository, WorkspaceRepository

        db = get_db()
        ws = WorkspaceRepository(db).get_by_id("default")
        if ws is None:
            WorkspaceRepository(db).create("default", "default")
        mid = str(uuid.uuid4())
        repo = MemoryRepository(db)
        repo.create(mid, "default", "my api key is sk-abc123xyzsecret", "general")

        resp = client.get(f"/console/memory/{mid}")
        html = resp.text
        assert "sk-abc123xyzsecret" not in html


class TestMemoryAuth:
    @pytest.fixture(autouse=True)
    def _save_restore_key(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    def test_auth_blocks_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-mem-key"
        resp = client.get("/console/memory")
        assert resp.status_code == 401

    def test_auth_blocks_wrong_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-mem-key"
        resp = client.get("/console/memory", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_auth_allows_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-mem-key"
        resp = client.get("/console/memory", headers={"Authorization": "Bearer test-mem-key"})
        assert resp.status_code == 200

    def test_auth_action_endpoints(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-mem-key"
        resp = client.post(
            "/console/memory/candidates/nonexistent/accept",
            headers={"Authorization": "Bearer test-mem-key"},
        )
        assert resp.status_code != 401
