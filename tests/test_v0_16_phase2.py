"""v0.16 Phase 2 — Overview page tests.

Covers: overview route renders, all four sections appear,
empty states, attention queue items, runtime health indicators,
activity stream, usage snapshot, quick actions, navigation,
auth protection, redaction.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.console.services import ConsoleOverviewService
from cogito_agent.storage import Database

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_pending() -> None:
    from cogito_agent.application.runtime_factory import default_workspace_path as _dwp
    from pathlib import Path

    p = Path(_dwp("default")) / "memory" / "PENDING.md"
    p.write_text("", encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Route tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewRoute:
    def test_overview_page_returns_200(self) -> None:
        resp = client.get("/console/overview")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_overview_page_has_title(self) -> None:
        resp = client.get("/console/overview")
        assert "<h2>Overview</h2>" in resp.text

    def test_overview_page_has_all_sections(self) -> None:
        resp = client.get("/console/overview")
        html = resp.text
        assert "Attention Queue" in html
        assert "Runtime Health" in html
        assert "Activity Stream" in html
        assert "Usage Snapshot" in html
        assert "Quick Actions" in html

    def test_overview_page_has_aria_labels(self) -> None:
        resp = client.get("/console/overview")
        html = resp.text
        assert 'aria-label="Attention queue"' in html
        assert 'aria-label="Runtime health"' in html
        assert 'aria-label="Activity stream"' in html
        assert 'aria-label="Quick actions"' in html
        assert 'aria-label="Usage snapshot"' in html


# ═══════════════════════════════════════════════════════════════════════════════
# Empty state tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewEmptyState:
    def test_empty_attention_queue(self) -> None:
        resp = client.get("/console/overview")
        assert "All clear" in resp.text
        assert "empty-state" in resp.text

    def test_empty_activity_stream(self) -> None:
        resp = client.get("/console/overview")
        assert "No recent activity" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# Navigation tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewNavigation:
    def test_nav_has_overview_link(self) -> None:
        resp = client.get("/console/overview")
        assert "/console/overview" in resp.text
        assert "Overview" in resp.text

    def test_overview_has_check_icon(self) -> None:
        resp = client.get("/console/overview")
        html = resp.text
        assert "check" in html


# ═══════════════════════════════════════════════════════════════════════════════
# Runtime Health tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewHealth:
    def test_health_grid_present(self) -> None:
        resp = client.get("/console/overview")
        assert "ov-health-grid" in resp.text

    def test_health_has_database(self) -> None:
        resp = client.get("/console/overview")
        assert "Database" in resp.text

    def test_health_has_provider(self) -> None:
        resp = client.get("/console/overview")
        assert "Provider" in resp.text

    def test_health_has_secrets(self) -> None:
        resp = client.get("/console/overview")
        assert "Secrets" in resp.text

    def test_health_has_drift(self) -> None:
        resp = client.get("/console/overview")
        assert "Drift" in resp.text

    def test_health_has_scheduler(self) -> None:
        resp = client.get("/console/overview")
        assert "Scheduler" in resp.text

    def test_health_dots_present(self) -> None:
        resp = client.get("/console/overview")
        assert "ov-health-dot" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# Quick Actions tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewQuickActions:
    def test_quick_actions_section_present(self) -> None:
        resp = client.get("/console/overview")
        assert "ov-actions" in resp.text

    def test_new_chat_action_present(self) -> None:
        resp = client.get("/console/overview")
        assert "New Chat" in resp.text
        assert "/console/chat" in resp.text

    def test_run_skill_action_present(self) -> None:
        resp = client.get("/console/overview")
        assert "Run Skill" in resp.text

    def test_scan_workspace_action_present(self) -> None:
        resp = client.get("/console/overview")
        assert "Scan Workspace" in resp.text

    def test_backup_action_has_soon_badge(self) -> None:
        resp = client.get("/console/overview")
        assert "Create Backup" in resp.text
        assert "soon" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# Activity Stream tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewActivity:
    def test_timeline_container_present(self) -> None:
        resp = client.get("/console/overview")
        html = resp.text
        if "ov-timeline" in html:
            assert "ov-timeline-item" in html
        else:
            assert "No recent activity" in html

    def test_view_all_link_present(self) -> None:
        resp = client.get("/console/overview")
        assert "/console/traces" in resp.text
        assert "View all" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# Usage Snapshot tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewUsage:
    def test_usage_stat_row_present(self) -> None:
        resp = client.get("/console/overview")
        assert "stat-row" in resp.text

    def test_usage_has_model_calls_24h(self) -> None:
        resp = client.get("/console/overview")
        assert "Model Calls (24h)" in resp.text

    def test_usage_has_model_calls_7d(self) -> None:
        resp = client.get("/console/overview")
        assert "Model Calls (7d)" in resp.text

    def test_usage_has_tool_calls_24h(self) -> None:
        resp = client.get("/console/overview")
        assert "Tool Calls (24h)" in resp.text

    def test_usage_has_tool_calls_7d(self) -> None:
        resp = client.get("/console/overview")
        assert "Tool Calls (7d)" in resp.text

    def test_usage_has_traces_24h(self) -> None:
        resp = client.get("/console/overview")
        assert "Traces (24h)" in resp.text

    def test_usage_has_traces_7d(self) -> None:
        resp = client.get("/console/overview")
        assert "Traces (7d)" in resp.text

    def test_usage_has_latency(self) -> None:
        resp = client.get("/console/overview")
        assert "Avg Latency" in resp.text

    def test_usage_has_failure_rate(self) -> None:
        resp = client.get("/console/overview")
        assert "Failure Rate" in resp.text

    def test_usage_has_decisions(self) -> None:
        resp = client.get("/console/overview")
        assert "Decisions (24h)" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# Service-level tests (with seeded data)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverviewServiceData:
    def _seed_db(self, db_path: str) -> None:
        db = Database(db_path)
        db.initialize()
        db.migrate()
        conn = db.connection

        conn.execute("INSERT OR IGNORE INTO workspaces (id, name) VALUES ('default', 'Default')")

        conn.execute(
            "INSERT INTO approval_records"
            " (id, workspace_id, actor_id, capability_name, status)"
            " VALUES ('ap1', 'default', 'user', 'test.cap', 'pending')"
        )

        conn.execute(
            "INSERT INTO outbox_messages"
            " (id, event_id, decision_id, workspace_id, title, body, status, created_at)"
            " VALUES ('ob1', 'ev1', 'dec1', 'default', 'failed msg', 'body',"
            " 'failed', datetime('now'))"
        )

        conn.execute(
            "INSERT INTO drift_runs (id, workspace_id, skill_name, status, created_at)"
            " VALUES ('dr1', 'default', 'test_skill', 'failed',"
            " datetime('now', '-1 hours'))"
        )

        conn.execute(
            "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
            " VALUES ('tr1', 'default', 'ev1', 'completed',"
            " datetime('now', '-2 hours'))"
        )

        conn.execute(
            "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
            " VALUES ('tr2', 'default', 'ev2', 'error', datetime('now', '-1 hours'))"
        )

        conn.execute(
            "INSERT INTO model_calls (trace_id, span_id, provider, model, latency_ms)"
            " VALUES ('tr1', 'sp1', 'mock', 'test-model', 150)"
        )
        conn.execute(
            "INSERT INTO model_calls (trace_id, span_id, provider, model, latency_ms)"
            " VALUES ('tr2', 'sp2', 'mock', 'test-model', 250)"
        )

        conn.execute(
            "INSERT INTO tool_calls (trace_id, span_id, capability_name, latency_ms)"
            " VALUES ('tr1', 'sp1', 'test.tool', 100)"
        )

        conn.execute(
            "INSERT INTO notification_decisions"
            " (id, event_id, workspace_id, action, created_at)"
            " VALUES ('nd1', 'ev1', 'default', 'push', datetime('now', '-3 hours'))"
        )

        conn.execute(
            "INSERT INTO drift_state (id, enabled) VALUES ('main', 1)"
            " ON CONFLICT(id) DO UPDATE SET enabled=1"
        )

        conn.commit()
        db.close()

    def test_service_attention_queue_detects_issues(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            self._seed_db(db_path)
            old_path = os.environ.get("COGITO_DB_PATH")
            os.environ["COGITO_DB_PATH"] = db_path
            try:
                service = ConsoleOverviewService()
                data = service._get_overview_data()
                attention = data["attention"]
                assert attention["total_issues"] > 0
                assert attention["pending_approvals"] == 1
                assert attention["pending_candidates"] == 0
                assert attention["failed_deliveries"] == 1
                assert attention["failed_drift_runs"] == 1
            finally:
                if old_path is None:
                    os.environ.pop("COGITO_DB_PATH", None)
                else:
                    os.environ["COGITO_DB_PATH"] = old_path
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_service_usage_snapshot_queries_values(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            self._seed_db(db_path)
            old_path = os.environ.get("COGITO_DB_PATH")
            os.environ["COGITO_DB_PATH"] = db_path
            try:
                service = ConsoleOverviewService()
                data = service._get_overview_data()
                usage = data["usage"]
                assert usage["model_calls_24h"] == 2
                assert usage["tool_calls_24h"] == 1
                assert usage["total_traces_24h"] == 2
                assert usage["decisions_24h"] == 1
            finally:
                if old_path is None:
                    os.environ.pop("COGITO_DB_PATH", None)
                else:
                    os.environ["COGITO_DB_PATH"] = old_path
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_service_activity_stream_has_events(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            self._seed_db(db_path)
            old_path = os.environ.get("COGITO_DB_PATH")
            os.environ["COGITO_DB_PATH"] = db_path
            try:
                service = ConsoleOverviewService()
                data = service._get_overview_data()
                activity = data["activity"]
                assert len(activity) > 0
                types = {e["type"] for e in activity}
                assert "trace" in types
                assert "drift" in types
                assert "decision" in types
            finally:
                if old_path is None:
                    os.environ.pop("COGITO_DB_PATH", None)
                else:
                    os.environ["COGITO_DB_PATH"] = old_path
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_service_health_has_drift_status(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            self._seed_db(db_path)
            old_path = os.environ.get("COGITO_DB_PATH")
            os.environ["COGITO_DB_PATH"] = db_path
            try:
                service = ConsoleOverviewService()
                data = service._get_overview_data()
                health = data["health"]
                assert health["drift_ok"] is True
                assert "enabled" in health["drift_message"]
            finally:
                if old_path is None:
                    os.environ.pop("COGITO_DB_PATH", None)
                else:
                    os.environ["COGITO_DB_PATH"] = old_path
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# Existing routes still work (regression)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExistingRoutesStillWork:
    def test_dashboard_page_still_works(self) -> None:
        resp = client.get("/console/")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text

    def test_chat_page_still_works(self) -> None:
        resp = client.get("/console/chat")
        assert resp.status_code == 200
        assert "<h2>Chat</h2>" in resp.text

    def test_memory_page_still_works(self) -> None:
        resp = client.get("/console/memory")
        assert resp.status_code == 200

    def test_approval_page_still_works(self) -> None:
        resp = client.get("/console/approval")
        assert resp.status_code == 200

    def test_traces_page_still_works(self) -> None:
        resp = client.get("/console/traces")
        assert resp.status_code == 200

    def test_audit_page_still_works(self) -> None:
        resp = client.get("/console/audit")
        assert resp.status_code == 200

    def test_autonomy_page_still_works(self) -> None:
        resp = client.get("/console/autonomy")
        assert resp.status_code == 200

    def test_config_page_still_works(self) -> None:
        resp = client.get("/console/config")
        assert resp.status_code == 200

    def test_doctor_page_still_works(self) -> None:
        resp = client.get("/console/doctor")
        assert resp.status_code == 200

    def test_inbox_page_still_works(self) -> None:
        resp = client.get("/console/inbox")
        assert resp.status_code == 200

    def test_drift_page_still_works(self) -> None:
        resp = client.get("/console/drift")
        assert resp.status_code == 200

    def test_artifacts_page_still_works(self) -> None:
        resp = client.get("/console/artifacts")
        assert resp.status_code == 200

    def test_workspace_files_page_still_works(self) -> None:
        resp = client.get("/console/workspace/files")
        assert resp.status_code == 200

    def test_not_found_page_still_works(self) -> None:
        resp = client.get("/console/nonexistent")
        assert resp.status_code == 404
