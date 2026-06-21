from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestAuditPage:
    def test_audit_page_returns_200(self) -> None:
        resp = client.get("/console/audit")
        assert resp.status_code == 200

    def test_empty_db_no_crash(self) -> None:
        resp = client.get("/console/audit")
        assert resp.status_code == 200

    def test_actor_filter(self) -> None:
        resp = client.get("/console/audit?actor=user")
        assert resp.status_code == 200

    def test_operation_filter(self) -> None:
        resp = client.get("/console/audit?operation=memory")
        assert resp.status_code == 200

    def test_search_filter(self) -> None:
        resp = client.get("/console/audit?q=test")
        assert resp.status_code == 200

    def test_time_range_filter(self) -> None:
        resp = client.get("/console/audit?time_range=24h")
        assert resp.status_code == 200

    def test_shows_audit_events(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.governance.audit import AuditLogger

        db = get_db()
        logger = AuditLogger(db)
        logger.log("user", "test_action", "test_resource", "default")

        resp = client.get("/console/audit")
        assert "test_action" in resp.text
        assert "test_resource" in resp.text


class TestAuditDetail:
    def test_detail_not_found(self) -> None:
        resp = client.get("/console/audit/nonexistent-audit-id")
        assert resp.status_code == 404

    def test_detail_returns_200(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.governance.audit import AuditLogger

        db = get_db()
        logger = AuditLogger(db)
        logger.log(
            "user",
            "test_action_detail",
            "test_resource_detail",
            "default",
            details='{"key": "value", "secret": "sk-mykey123"}',
        )

        cur = db.connection.execute(
            "SELECT id FROM audit_logs WHERE action=? ORDER BY created_at DESC LIMIT 1",
            ("test_action_detail",),
        )
        row = cur.fetchone()
        assert row is not None
        aid = row["id"]

        resp = client.get(f"/console/audit/{aid}")
        assert resp.status_code == 200
        assert "test_action_detail" in resp.text

    def test_detail_redacts_secrets(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.governance.audit import AuditLogger

        db = get_db()
        logger = AuditLogger(db)
        logger.log(
            "assistant",
            "call_tool",
            "workspace_file",
            "default",
            details='{"operation": "write", "path": "sk-abc123secret"}',
        )

        cur = db.connection.execute(
            "SELECT id FROM audit_logs WHERE action=? ORDER BY created_at DESC LIMIT 1",
            ("call_tool",),
        )
        row = cur.fetchone()
        assert row is not None
        aid = row["id"]

        resp = client.get(f"/console/audit/{aid}")
        html = resp.text
        assert "sk-abc123secret" not in html


class TestAuditSecurity:
    def test_no_stack_trace_on_404(self) -> None:
        resp = client.get("/console/audit/nonexistent")
        html = resp.text
        assert "Traceback" not in html
        assert 'File "' not in html

    def test_audit_xss_escape(self) -> None:
        from cogito_agent.api.app import get_db
        from cogito_agent.governance.audit import AuditLogger

        db = get_db()
        logger = AuditLogger(db)
        logger.log(
            "user",
            '<script>alert("xss")</script>',
            "test_resource",
            "default",
        )

        cur = db.connection.execute(
            "SELECT id FROM audit_logs WHERE action LIKE '%script%'"
            " ORDER BY created_at DESC LIMIT 1",
        )
        row = cur.fetchone()
        assert row is not None
        aid = row["id"]

        resp = client.get(f"/console/audit/{aid}")
        html = resp.text
        # User-controlled action must be HTML-escaped
        assert "&lt;script&gt;alert" in html or "redacted" in html.lower()
        # Raw user-controlled content should NOT appear
        assert '<script>alert("xss")</script>' not in html


class TestAuditAuth:
    @pytest.fixture(autouse=True)
    def _save_restore_key(self) -> Any:
        saved = os.environ.get("COGITO_API_KEY")
        yield
        if saved is not None:
            os.environ["COGITO_API_KEY"] = saved
        else:
            os.environ.pop("COGITO_API_KEY", None)

    def test_auth_blocks_no_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-audit-key"
        resp = client.get("/console/audit")
        assert resp.status_code == 401

    def test_auth_allows_valid_token(self) -> None:
        os.environ["COGITO_API_KEY"] = "test-audit-key"
        resp = client.get("/console/audit", headers={"Authorization": "Bearer test-audit-key"})
        assert resp.status_code == 200
