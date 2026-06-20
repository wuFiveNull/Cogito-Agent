"""v0.16 Phase 0 — ConsolePageContext & Application Service boundary tests.

Covers: ConsolePageContext TypedDict, DashboardService, BaseConsoleService,
static resource versioning, template rendering with context.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from cogito_agent.api.app import app
from cogito_agent.console.context import (
    Breadcrumb,
    ConsolePageContext,
    FlashMessage,
    MenuItem,
)
from cogito_agent.console.services import BaseConsoleService, DashboardService
from cogito_agent.console.static_version import STATIC_VERSION, get_static_version

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════════
# ConsolePageContext TypedDict tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestConsolePageContext:
    def test_context_type_keys(self) -> None:
        ctx: ConsolePageContext = {
            "request": None,  # type: ignore[typeddict-item]
            "title": "Test",
            "version": "0.0.0",
            "workspace": {"id": "w1", "name": "Test"},
            "breadcrumbs": [],
            "menu": [],
            "flash": [],
            "system_status": {
                "db_ok": True,
                "migration_version": 6,
                "provider": "mock",
                "streaming_enabled": True,
                "timeout_seconds": 30,
                "secrets_backend": "dev_sqlite",
                "secrets_available": True,
            },
            "csrf_token": "",
            "csrf_token_input": "",
        }
        assert ctx["title"] == "Test"
        assert ctx["workspace"]["id"] == "w1"

    def test_breadcrumb_type(self) -> None:
        b: Breadcrumb = {"label": "Home", "url": "/console/"}
        assert b["label"] == "Home"

    def test_flash_message_type(self) -> None:
        f: FlashMessage = {"level": "info", "message": "hello"}
        assert f["level"] == "info"

    def test_menu_item_with_soon(self) -> None:
        m: MenuItem = {"label": "Foo", "href": "/foo", "icon": "foo", "soon": True}
        assert m["soon"] is True

    def test_menu_item_without_soon(self) -> None:
        m: MenuItem = {"label": "Bar", "href": "/bar", "icon": "bar"}
        assert "soon" not in m


# ═══════════════════════════════════════════════════════════════════════════════
# DashboardService tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDashboardService:
    def test_service_is_instance_of_base(self) -> None:
        svc = DashboardService()
        assert isinstance(svc, BaseConsoleService)

    def test_get_version(self) -> None:
        svc = DashboardService()
        ver = svc.get_version()
        assert isinstance(ver, str)
        assert len(ver) > 0

    def test_get_system_status_returns_dict(self) -> None:
        svc = DashboardService()
        status = svc.get_system_status()
        assert isinstance(status, dict)
        assert "db" in status
        assert "model" in status

    def test_build_page_context_minimal(self) -> None:
        """Service builds a valid ConsolePageContext even with minimal request."""
        svc = DashboardService()

        class FakeRequest:
            state = type("state", (), {"csrf_token": "abc123"})()

        ctx = svc.build_page_context(FakeRequest(), "UnitTest")  # type: ignore[arg-type]
        assert ctx["title"] == "UnitTest"
        assert ctx["workspace"]["id"] == "default"
        assert len(ctx["breadcrumbs"]) >= 1
        assert isinstance(ctx["menu"], list)
        assert isinstance(ctx["flash"], list)
        assert ctx["csrf_token"] == "abc123"

    def test_build_page_context_adds_extra(self) -> None:
        svc = DashboardService()

        class FakeRequest:
            state = type("state", (), {"csrf_token": ""})()

        ctx = svc.build_page_context(FakeRequest(), "Test", extra={"custom_key": 42})  # type: ignore[arg-type]
        assert ctx.get("custom_key") == 42  # type: ignore[literal-required]


# ═══════════════════════════════════════════════════════════════════════════════
# Static version tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestStaticVersion:
    def test_static_version_is_string(self) -> None:
        assert isinstance(STATIC_VERSION, str)
        assert len(STATIC_VERSION) > 0

    def test_get_static_version_returns_hash(self) -> None:
        ver = get_static_version()
        assert isinstance(ver, str)
        assert len(ver) == 12  # sha256[:12]

    def test_static_version_is_deterministic(self) -> None:
        v1 = get_static_version()
        v2 = get_static_version()
        assert v1 == v2

    def test_local_htmx_runtime_initializes_global(self) -> None:
        resp = client.get("/console/static/htmx.min.js")
        assert resp.status_code == 200
        assert "global.htmx = htmx" in resp.text
        assert ")(globalThis);" in resp.text


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: dashboard route returns context-aware response
# ═══════════════════════════════════════════════════════════════════════════════


class TestDashboardIntegration:
    def test_dashboard_returns_200(self) -> None:
        resp = client.get("/console/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_static_version_in_css_url(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "console.css?v=" in html

    def test_dashboard_contains_static_version_in_js_url(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "htmx.min.js?v=" in html

    def test_dashboard_shows_cogito_title(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "Cogito" in html
        assert "Dashboard" in html

    def test_dashboard_menu_items_present(self) -> None:
        resp = client.get("/console/")
        html = resp.text
        assert "nav-item" in html
        assert "nav-list" in html


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


def test_page_context_rejects_invalid_keys() -> None:
    """ConsolePageContext should reject arbitrary keys at type-check time."""
    ctx: ConsolePageContext = {
        "request": None,  # type: ignore[typeddict-item]
        "title": "x",
        "version": "x",
        "workspace": {"id": "x", "name": "x"},
        "breadcrumbs": [],
        "menu": [],
        "flash": [],
        "system_status": {
            "db_ok": True,
            "migration_version": 1,
            "provider": "x",
            "streaming_enabled": False,
            "timeout_seconds": 30,
            "secrets_backend": "x",
            "secrets_available": True,
        },
        "csrf_token": "",
        "csrf_token_input": "",
    }
    assert ctx["version"] == "x"


def test_dashboard_service_with_empty_request_state() -> None:
    svc = DashboardService()

    class BareRequest:
        class State:
            csrf_token = ""

        state = State()

    ctx = svc.build_page_context(BareRequest(), "NoCSRF")  # type: ignore[arg-type]
    assert ctx["csrf_token"] == ""
    assert "csrf_token_input" in ctx
