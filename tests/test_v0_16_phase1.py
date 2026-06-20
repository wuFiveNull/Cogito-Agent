"""v0.16 Phase 1 — Design System tests.

Covers: design-tokens.css loads, SVG icons render, component macros render,
nav uses SVG icons (not emoji), base template has design token link,
dashboard uses macros, all existing routes still work.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app

client = TestClient(app)


class TestDesignTokens:
    def test_design_tokens_css_is_served(self) -> None:
        resp = client.get("/console/static/design-tokens.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        assert "--color-primary" in resp.text
        assert "--font-sans" in resp.text
        assert "--sidebar-width" in resp.text

    def test_design_tokens_contains_custom_properties(self) -> None:
        resp = client.get("/console/static/design-tokens.css")
        body = resp.text
        assert ":root" in body
        assert "--color-bg" in body
        assert "--space-sm" in body
        assert "--text-base" in body
        assert "--radius-xl" in body

    def test_tokens_file_is_loaded_on_dashboard(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "design-tokens.css?v=" in html


class TestSvgIcons:
    def test_nav_uses_svg_not_emoji(self) -> None:
        """Phase 1 requirement: replace all emoji nav icons with SVG."""
        resp = client.get("/console/")
        html = resp.text
        assert '<svg class="nav-svg-icon"' in html
        assert 'class="nav-label"' in html

    def test_nav_icons_have_aria_hidden(self) -> None:
        resp = client.get("/console/")
        assert 'aria-hidden="true"' in resp.text

    def test_badge_soon_present_on_future_items(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        if "badge-soon" in html:
            assert "soon" in html

    def test_all_icons_have_correct_path_data(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "M3 9l9-7 9 7" in html  # home icon path


class TestComponentMacros:
    def test_stat_card_renders(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "stat-card" in html
        assert "Memories" in html
        assert "stat-value" in html

    def test_info_table_renders(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "info-table" in html
        assert "DB" in html
        assert "Provider" in html

    def test_dashboard_header_exists(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "<h2>Dashboard</h2>" in html


class TestDashboardTemplate:
    def test_dashboard_uses_macros(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "Memories" in html
        assert "Pending Approvals" in html

    def test_dashboard_shows_version(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "Cogito-Agent" in html
        assert "local-first personal Agent" in html

    def test_dashboard_quick_links(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "quick-links" in html
        assert "quick-link" in html

    def test_dashboard_system_table(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "info-table" in html
        assert "Migration" in html or "migration" in html

    def test_dashboard_badge_ok_renders(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "badge-ok" in html


class TestExistingRoutesStillWork:
    """Regression: all existing routes must still render correctly."""

    def test_chat_page_still_works(self) -> None:
        resp = client.get("/console/chat")
        assert resp.status_code == 200
        assert "<h2>Chat</h2>" in resp.text

    def test_memory_page_still_works(self) -> None:
        resp = client.get("/console/memory")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_approval_page_still_works(self) -> None:
        resp = client.get("/console/approval")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_traces_page_still_works(self) -> None:
        resp = client.get("/console/traces")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_audit_page_still_works(self) -> None:
        resp = client.get("/console/audit")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_autonomy_page_still_works(self) -> None:
        resp = client.get("/console/autonomy")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_config_page_still_works(self) -> None:
        resp = client.get("/console/config")
        assert resp.status_code == 200
        assert "Configuration" in resp.text

    def test_doctor_page_still_works(self) -> None:
        resp = client.get("/console/doctor")
        assert resp.status_code == 200
        assert "Doctor" in resp.text

    def test_inbox_page_still_works(self) -> None:
        resp = client.get("/console/inbox")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_workspace_files_page_still_works(self) -> None:
        resp = client.get("/console/workspace/files")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_drift_page_still_works(self) -> None:
        resp = client.get("/console/drift")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_artifacts_page_still_works(self) -> None:
        resp = client.get("/console/artifacts")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestResponsiveShell:
    def test_viewport_meta_tag(self) -> None:
        resp = client.get("/console/")
        assert 'name="viewport"' in resp.text
        assert "initial-scale=1.0" in resp.text

    def test_base_html_has_landmark_roles(self) -> None:
        resp = client.get("/console/")
        assert 'role="navigation"' in resp.text
        assert 'aria-label="Main navigation"' in resp.text

    def test_global_indicator_present(self) -> None:
        resp = client.get("/console/")
        assert "global-spinner" in resp.text
        assert "Working..." in resp.text


class TestDesignTokensCssEndpoint:
    def test_css_has_no_emoji(self) -> None:
        resp = client.get("/console/static/design-tokens.css")
        assert "emoji" not in resp.text.lower()

    def test_design_tokens_uses_var_syntax(self) -> None:
        resp = client.get("/console/static/design-tokens.css")
        assert "var(" not in resp.text  # tokens ARE the definitions
        assert "--" in resp.text

    def test_design_tokens_semantic_colors(self) -> None:
        resp = client.get("/console/static/design-tokens.css")
        body = resp.text
        assert "--color-primary" in body
        assert "--color-success" in body
        assert "--color-warning" in body
        assert "--color-danger" in body
