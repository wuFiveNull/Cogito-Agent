from __future__ import annotations

from typing import Any

from fastapi import Request

from cogito_agent.console.context import (
    ConsolePageContext,
    MenuItem,
    SystemStatusSummary,
    WorkspaceSummary,
)
from cogito_agent.console.status import build_status
from cogito_agent.console.utils import csrf_token_input
from cogito_agent.console.utils import menu_items as _menu_items
from cogito_agent.version import APP_VERSION

from .base import BaseConsoleService


class DashboardService(BaseConsoleService):
    def build_page_context(
        self,
        request: Request,
        title: str,
        extra: dict[str, object] | None = None,
    ) -> ConsolePageContext:
        status_data = build_status()
        csrf_val = getattr(request.state, "csrf_token", "")
        ctx: ConsolePageContext = {
            "request": request,
            "title": title,
            "version": self.get_version(),
            "workspace": self._build_workspace_summary(),
            "breadcrumbs": [{"label": "Dashboard", "url": "/console/"}],
            "menu": self._build_menu("Dashboard"),
            "flash": [],
            "system_status": self._build_system_status_summary(status_data),
            "csrf_token": csrf_val,
            "csrf_token_input": csrf_token_input(request),
        }
        if extra:
            for key, value in extra.items():
                if key not in ctx or key.startswith("_"):
                    ctx[key] = value  # type: ignore[literal-required]
        return ctx

    def get_version(self) -> str:
        return APP_VERSION

    def get_system_status(self) -> dict[str, Any]:
        return build_status()

    # ── helpers ─────────────────────────────────────────────────────────

    def _build_workspace_summary(self) -> WorkspaceSummary:
        return {"id": "default", "name": "Default Workspace"}

    def _build_system_status_summary(
        self, status_data: dict[str, Any]
    ) -> SystemStatusSummary:
        db_info = status_data.get("db", {})
        model_info = status_data.get("model", {})
        secrets_info = status_data.get("secrets", {})
        return {
            "db_ok": bool(db_info.get("ok", False)),
            "migration_version": int(db_info.get("migration_version", 0)),
            "provider": str(model_info.get("provider", "unknown")),
            "streaming_enabled": bool(model_info.get("streaming_enabled", False)),
            "timeout_seconds": int(model_info.get("timeout_seconds", 30)),
            "secrets_backend": str(secrets_info.get("backend", "none")),
            "secrets_available": bool(secrets_info.get("available", False)),
        }

    def _build_menu(self, active_label: str | None = None) -> list[MenuItem]:
        return _menu_items()
