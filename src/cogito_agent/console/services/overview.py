from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import Request

from cogito_agent.console.context import (
    ConsolePageContext,
    MenuItem,
    SystemStatusSummary,
)
from cogito_agent.console.status import build_status
from cogito_agent.console.utils import csrf_token_input
from cogito_agent.console.utils import menu_items as _menu_items
from cogito_agent.storage import Database
from cogito_agent.storage import get_db as _get_db
from cogito_agent.storage.repositories import (
    ApprovalRepository,
    DecisionRepository,
    DriftRunRepository,
    DriftStateRepository,
    MemoryItemRepository,
    ModelCallRepository,
    OutboxRepository,
    ToolCallRepository,
    TraceRepository,
)
from cogito_agent.version import APP_VERSION

from .base import BaseConsoleService


class ConsoleOverviewService(BaseConsoleService):
    def __init__(self) -> None:
        self._db: Database | None = None

    def _get_db(self) -> Database:
        return _get_db()

    def build_page_context(
        self,
        request: Request,
        title: str,
        extra: dict[str, object] | None = None,
    ) -> ConsolePageContext:
        status_data = build_status()
        csrf_val = getattr(request.state, "csrf_token", "")
        overview_data = self._get_overview_data()

        ctx: ConsolePageContext = {
            "request": request,
            "title": title,
            "version": self.get_version(),
            "workspace": {"id": "default", "name": "Default Workspace"},
            "breadcrumbs": [{"label": "Overview", "url": "/console/overview"}],
            "menu": self._build_menu("Overview"),
            "flash": [],
            "system_status": self._build_system_status_summary(status_data),
            "csrf_token": csrf_val,
            "csrf_token_input": csrf_token_input(request),
        }

        page_data = cast(dict[str, object], ctx)
        page_data["overview"] = overview_data
        page_data["status"] = status_data
        if extra:
            page_data.update(extra)
        return cast(ConsolePageContext, page_data)

    def get_version(self) -> str:
        return APP_VERSION

    def get_system_status(self) -> dict[str, Any]:
        return build_status()

    def _get_overview_data(self) -> dict[str, Any]:
        return {
            "attention": self._get_attention_queue(),
            "health": self._get_runtime_health(),
            "activity": self._get_activity_stream(limit=20),
            "usage": self._get_usage_snapshot(),
            "quick_actions": self._get_quick_actions(),
        }

    def _get_attention_queue(self) -> dict[str, Any]:
        db = self._get_db()
        pending_approvals: list[dict[str, Any]] = []
        failed_deliveries = 0
        failed_delivery_items: list[dict[str, Any]] = []
        pending_candidates: list[dict[str, Any]] = []
        failed_drift_runs = 0
        failed_drift_items: list[dict[str, Any]] = []

        try:
            approval_repo = ApprovalRepository(db)
            pending_approvals = approval_repo.list_pending("default")
        except Exception:
            pending_approvals = []

        try:
            outbox_repo = OutboxRepository(db)
            failed_deliveries = outbox_repo.count_by_status(("failed", "dead_letter"))
            failed_delivery_items = outbox_repo.list_failed(limit=5)
        except Exception:
            failed_deliveries = 0
            failed_delivery_items = []

        try:
            mem_repo = MemoryItemRepository(db)
            rows = mem_repo.list_active(
                "default", exclude_type="_recent_context", limit=10
            )
            pending_candidates = [{
                "id": str(r["id"])[:16],
                "text": str(r["summary"]),
                "type": str(r["memory_type"]),
            } for r in rows]
        except Exception:
            pending_candidates = []

        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        try:
            drift_repo = DriftRunRepository(db)
            failed_drift_runs = drift_repo.count_failed(since=cutoff)
            failed_drift_items = drift_repo.list_failed(since=cutoff, limit=5)
        except Exception:
            failed_drift_runs = 0
            failed_drift_items = []

        total_issues = (
            len(pending_approvals) + failed_deliveries + len(pending_candidates) + failed_drift_runs
        )

        return {
            "pending_approvals": len(pending_approvals),
            "pending_approval_items": pending_approvals[:5],
            "failed_deliveries": failed_deliveries,
            "failed_delivery_items": failed_delivery_items,
            "pending_candidates": len(pending_candidates),
            "pending_candidate_items": pending_candidates[:5],
            "failed_drift_runs": failed_drift_runs,
            "failed_drift_items": failed_drift_items,
            "total_issues": total_issues,
        }

    def _get_runtime_health(self) -> dict[str, Any]:
        status_data = build_status()
        db_info = cast(dict[str, Any], status_data.get("db", {}))
        model_info = cast(dict[str, Any], status_data.get("model", {}))
        secrets_info = cast(dict[str, Any], status_data.get("secrets", {}))

        drift_ok = False
        drift_msg = "Drift runtime not available"
        try:
            drift_state_repo = DriftStateRepository(self._get_db())
            row = drift_state_repo.get()
            if row is not None:
                drift_ok = True
                drift_msg = f"Drift {'enabled' if row['enabled'] else 'disabled'}"
        except Exception:
            pass

        return {
            "db_ok": bool(db_info.get("ok", False)),
            "db_migration": int(db_info.get("migration_version", 0)),
            "provider": str(model_info.get("provider", "unknown")),
            "streaming": bool(model_info.get("streaming_enabled", False)),
            "secrets_backend": str(secrets_info.get("backend", "none")),
            "secrets_available": bool(secrets_info.get("available", False)),
            "drift_ok": drift_ok,
            "drift_message": drift_msg,
            "scheduler_ok": False,
            "scheduler_message": "Not implemented",
        }

    def _get_activity_stream(self, limit: int = 20) -> list[dict[str, Any]]:
        db = self._get_db()
        events: list[dict[str, Any]] = []

        try:
            trace_repo = TraceRepository(db)
            for row in trace_repo.list_by_workspace("default", limit=10):
                events.append({
                    "type": "trace",
                    "id": row["id"],
                    "status": row["status"],
                    "timestamp": row["started_at"],
                    "summary": f"Trace {row['status']}",
                    "url": f"/console/traces/{row['id']}",
                })
        except Exception:
            pass

        try:
            drift_repo = DriftRunRepository(db)
            for row in drift_repo.list_by_workspace("default", limit=5):
                events.append({
                    "type": "drift",
                    "id": row["id"],
                    "status": row["status"],
                    "timestamp": row["created_at"],
                    "summary": f"Drift: {row['skill_name']} ({row['status']})",
                    "url": f"/console/drift/runs/{row['id']}",
                })
        except Exception:
            pass

        try:
            from cogito_agent.autonomy.store import DecisionStore

            store = DecisionStore(db)
            decisions = store.list_decisions(workspace_id="*", limit=5)
            for dec in decisions:
                events.append({
                    "type": "decision",
                    "id": dec["id"],
                    "status": dec.get("action", ""),
                    "timestamp": dec.get("created_at", ""),
                    "summary": f"Decision: {dec.get('action', 'unknown')}",
                    "url": f"/console/autonomy/decisions/{dec['id']}",
                })
        except Exception:
            pass

        try:
            from cogito_agent.workspace.artifacts import ArtifactService

            artifact_service = ArtifactService(db)
            artifacts = artifact_service.list_artifacts(workspace_id="default", limit=5)
            for art in artifacts:
                events.append({
                    "type": "artifact",
                    "id": art["id"],
                    "status": "created",
                    "timestamp": art.get("created_at", ""),
                    "summary": f"Artifact: {art.get('title', 'untitled')}",
                    "url": f"/console/artifacts/{art['id']}",
                })
        except Exception:
            pass

        events.sort(
            key=lambda e: str(e.get("timestamp", "") or ""),
            reverse=True,
        )

        return events[:limit]

    def _get_usage_snapshot(self) -> dict[str, Any]:
        db = self._get_db()
        now = datetime.now(UTC)
        cutoff_24h = (now - timedelta(hours=24)).isoformat()
        cutoff_7d = (now - timedelta(days=7)).isoformat()

        model_calls_24h = 0
        model_calls_7d = 0
        tool_calls_24h = 0
        tool_calls_7d = 0
        avg_latency_24h = 0.0
        total_traces_24h = 0
        total_traces_7d = 0
        failure_rate_24h = 0.0
        decisions_24h = 0

        try:
            mc_repo = ModelCallRepository(db)
            model_calls_24h = mc_repo.count_by_time_range(cutoff_24h)
            model_calls_7d = mc_repo.count_by_time_range(cutoff_7d)
            avg_latency_24h = mc_repo.avg_latency(cutoff_24h)
        except Exception:
            pass

        try:
            tc_repo = ToolCallRepository(db)
            tool_calls_24h = tc_repo.count_by_time_range(cutoff_24h)
            tool_calls_7d = tc_repo.count_by_time_range(cutoff_7d)
        except Exception:
            pass

        try:
            trace_repo = TraceRepository(db)
            total_traces_24h = trace_repo.count_by_time_range(cutoff_24h)
            total_traces_7d = trace_repo.count_by_time_range(cutoff_7d)
            failed = trace_repo.count_failed_by_time_range(cutoff_24h)
            failure_rate_24h = (
                round(failed / total_traces_24h * 100, 1) if total_traces_24h > 0 else 0.0
            )
        except Exception:
            pass

        try:
            decision_repo = DecisionRepository(db)
            decisions_24h = decision_repo.count_by_time_range(cutoff_24h)
        except Exception:
            pass

        return {
            "model_calls_24h": model_calls_24h,
            "model_calls_7d": model_calls_7d,
            "tool_calls_24h": tool_calls_24h,
            "tool_calls_7d": tool_calls_7d,
            "avg_latency_24h": avg_latency_24h,
            "failure_rate_24h": failure_rate_24h,
            "total_traces_24h": total_traces_24h,
            "total_traces_7d": total_traces_7d,
            "decisions_24h": decisions_24h,
        }

    def _get_quick_actions(self) -> list[dict[str, str | bool]]:
        return [
            {
                "label": "New Chat",
                "href": "/console/chat",
                "icon": "chat",
                "desc": "Start a new conversation",
            },
            {
                "label": "Run Skill",
                "href": "/console/drift",
                "icon": "drift",
                "desc": "Trigger a skill run",
            },
            {
                "label": "Scan Workspace",
                "href": "/console/workspace/files",
                "icon": "file",
                "desc": "Index workspace files",
            },
            {
                "label": "Create Backup",
                "href": "",
                "icon": "config",
                "desc": "Use CLI: cogito backup create",
                "soon": True,
            },
        ]

    def _build_menu(self, active_label: str | None = None) -> list[MenuItem]:
        return _menu_items()

    def _build_system_status_summary(self, status_data: dict[str, Any]) -> SystemStatusSummary:
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
