from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from cogito_agent.governance import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    SessionRepository,
    WorkspaceRepository,
    WorkspaceSettingsRepository,
)


class WorkspaceApplicationService:
    def __init__(self, db: Database, audit: AuditLogger | None = None) -> None:
        self._db = db
        self._workspaces = WorkspaceRepository(db)
        self._sessions = SessionRepository(db)
        self._settings = WorkspaceSettingsRepository(db)
        self._audit = audit or AuditLogger(db)

    def ensure_workspace(self, workspace_id: str, name: str | None = None) -> dict[str, object]:
        existing = self._workspaces.get_by_id(workspace_id)
        if existing is not None:
            return existing
        return self._workspaces.create(workspace_id, name or workspace_id)

    def create_workspace(
        self,
        name: str,
        *,
        workspace_id: str | None = None,
        actor_id: str = "api",
    ) -> dict[str, object]:
        wid = workspace_id or str(uuid.uuid4())
        result = self._workspaces.create(wid, name)
        self._log(actor_id, "workspace.create", wid, wid)
        return result

    def delete_workspace(self, workspace_id: str, *, actor_id: str = "api") -> bool:
        if self._workspaces.get_by_id(workspace_id) is None:
            return False
        self._workspaces.soft_delete(workspace_id)
        self._log(actor_id, "workspace.delete", workspace_id, workspace_id)
        return True

    def create_session(
        self,
        workspace_id: str,
        title: str,
        *,
        session_id: str | None = None,
        actor_id: str = "api",
    ) -> dict[str, object]:
        self.ensure_workspace(workspace_id)
        sid = session_id or str(uuid.uuid4())
        result = self._sessions.create(sid, workspace_id, title)
        self._log(actor_id, "session.create", sid, workspace_id)
        return result

    def update_settings(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        quiet_hours_start: str | None = None,
        quiet_hours_end: str | None = None,
        timezone: str | None = None,
        max_daily_notifications: int | None = None,
        actor_id: str = "api",
    ) -> dict[str, object]:
        if name is not None:
            self._workspaces.rename(workspace_id, name)
        values: dict[str, str | int] = {}
        for key, value in (
            ("quiet_hours_start", quiet_hours_start),
            ("quiet_hours_end", quiet_hours_end),
            ("timezone", timezone),
            ("max_daily_notifications", max_daily_notifications),
        ):
            if value is not None:
                values[key] = value
        result = self._settings.upsert(workspace_id, **values)
        self._log(actor_id, "workspace.settings.update", workspace_id, workspace_id)
        return result

    def cleanup(
        self,
        workspace_id: str,
        *,
        retention_days: int = 90,
        actor_id: str = "api",
    ) -> dict[str, int]:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        from cogito_agent.storage.repositories import SessionRepository, TraceRepository
        sessions_repo = SessionRepository(self._db)
        traces_repo = TraceRepository(self._db)
        deleted_sessions = sessions_repo.cleanup_soft_deleted_before(workspace_id, cutoff)
        deleted_traces = traces_repo.cleanup_old_traces_before(workspace_id, cutoff)
        self._log(actor_id, "workspace.cleanup", workspace_id, workspace_id)
        return {
            "deleted_sessions": deleted_sessions,
            "deleted_traces": deleted_traces,
        }

    def _log(
        self,
        actor_id: str,
        action: str,
        resource_id: str,
        workspace_id: str,
    ) -> None:
        self._audit.log(
            actor_id=actor_id,
            action=action,
            resource=f"workspace:{resource_id}",
            workspace_id=workspace_id,
            decision="allow",
        )
