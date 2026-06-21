from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestApprovalSecurity:
    def test_no_stack_trace(self) -> None:
        resp = client.post("/console/approval/nonexistent/approve")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_error_no_api_key_leak(self) -> None:
        resp = client.post("/console/approval/nonexistent/approve")
        html = resp.text
        assert "sk-" not in html.replace("[REDACTED", "")

    def test_approval_resource_redacted(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.storage.repositories import ApprovalRepository

        db = get_db()
        repo = ApprovalRepository(db)
        rec = repo.create(
            "default",
            "user",
            "test_tool",
            "write",
            "my api key is sk-abc123secret",
            "test reason",
        )
        aid = str(rec["id"])

        resp = client.get(f"/console/approval/{aid}")
        html = resp.text
        assert "sk-abc123secret" not in html

    def test_html_escape_on_resource(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.storage.repositories import ApprovalRepository

        db = get_db()
        repo = ApprovalRepository(db)
        rec = repo.create(
            "default",
            "user",
            "test_tool",
            "write",
            '<script>alert("xss")</script>',
            "test",
        )
        aid = str(rec["id"])

        resp = client.get(f"/console/approval/{aid}")
        html = resp.text
        # User-controlled resource must be HTML-escaped
        assert "&lt;script&gt;alert" in html
        # Raw user-controlled content should NOT appear
        assert '<script>alert("xss")</script>' not in html


class TestApprovalAuth:
    @pytest.fixture(autouse=True)
    def _save_restore_key(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    def test_auth_blocks_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-approval-key"
        resp = client.get("/console/approval")
        assert resp.status_code == 401

    def test_auth_blocks_wrong_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-approval-key"
        resp = client.get("/console/approval", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_auth_allows_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-approval-key"
        resp = client.get(
            "/console/approval", headers={"Authorization": "Bearer test-approval-key"}
        )
        assert resp.status_code == 200

    def test_auth_action_endpoints(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-approval-key"
        resp = client.post(
            "/console/approval/nonexistent/approve",
            headers={"Authorization": "Bearer test-approval-key"},
        )
        assert resp.status_code != 401
