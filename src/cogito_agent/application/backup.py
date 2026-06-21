from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from cogito_agent.cli.backup import create_backup, restore_backup


class BackupAuditPort(Protocol):
    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str = "",
        reason: str = "",
        details: str = "{}",
        redact_details: bool = True,
    ) -> str: ...


class BackupApplicationService:
    """Safe local backup workflow restricted to one configured directory."""

    def __init__(
        self,
        *,
        db_path: str,
        backup_dir: str,
        audit: BackupAuditPort | None = None,
        reset_before_restore: Callable[[], None] | None = None,
        restore_completed: Callable[[str, str], None] | None = None,
    ) -> None:
        self._db_path = str(Path(db_path).expanduser()) if db_path != ":memory:" else db_path
        self._backup_dir = Path(backup_dir).expanduser().resolve()
        self._audit = audit
        self._reset_before_restore = reset_before_restore
        self._restore_completed = restore_completed

    @property
    def available(self) -> bool:
        return self._db_path != ":memory:"

    def list_backups(self) -> list[dict[str, object]]:
        if not self._backup_dir.exists():
            return []
        return [
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=UTC,
                ).isoformat(),
            }
            for path in sorted(
                self._backup_dir.glob("*.zip"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if path.is_file()
        ]

    def create(self, *, workspace_id: str, actor_id: str = "console") -> dict[str, Any]:
        self._require_file_database()
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        target = self._backup_dir / f"cogito_{timestamp}.zip"
        result = create_backup(
            str(target),
            db_path=self._db_path,
            include_secrets=False,
            data_dir=str(Path(self._db_path).parent),
        )
        self._log(actor_id, "backup.create", target.name, workspace_id, "created")
        return result

    def preflight(self, name: str) -> dict[str, Any]:
        self._require_file_database()
        source = self._resolve_backup(name)
        return restore_backup(
            str(source),
            db_path=self._db_path,
            dry_run=True,
            data_dir=str(Path(self._db_path).parent),
        )

    def restore(
        self,
        name: str,
        *,
        confirmation: str,
        workspace_id: str,
        actor_id: str = "console",
    ) -> dict[str, Any]:
        self._require_file_database()
        if confirmation != name:
            raise ValueError("Confirmation must exactly match the backup filename")
        source = self._resolve_backup(name)
        preflight = self.preflight(name)
        if preflight.get("errors"):
            return preflight
        self._log(actor_id, "backup.restore", name, workspace_id, "preflight passed")
        if self._reset_before_restore is not None:
            self._reset_before_restore()
        result = restore_backup(
            str(source),
            db_path=self._db_path,
            dry_run=False,
            data_dir=str(Path(self._db_path).parent),
        )
        if self._restore_completed is not None:
            self._restore_completed(name, workspace_id)
        return result

    def _resolve_backup(self, name: str) -> Path:
        if not name or Path(name).name != name or not name.lower().endswith(".zip"):
            raise ValueError("Invalid backup filename")
        candidate = (self._backup_dir / name).resolve()
        if candidate.parent != self._backup_dir or not candidate.is_file():
            raise ValueError("Backup does not exist in the configured backup directory")
        return candidate

    def _require_file_database(self) -> None:
        if not self.available:
            raise RuntimeError("Backups require a file-backed SQLite database")

    def _log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        reason: str,
    ) -> None:
        if self._audit is None:
            return
        self._audit.log(
            actor_id=actor_id,
            action=action,
            resource=f"backup:{resource}",
            workspace_id=workspace_id,
            decision="allow",
            reason=reason,
        )
