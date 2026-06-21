from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cogito_agent.cli.backup import create_backup
from cogito_agent.config import StorageSettings
from cogito_agent.storage import Database


class MaintenanceWorker:
    """Periodic SQLite maintenance and bounded local backup worker."""

    def __init__(self, settings: StorageSettings) -> None:
        self._settings = settings
        self._stop_event = threading.Event()

    def run_once(self, *, include_backup: bool = True) -> dict[str, Any]:
        db_path = str(Path(self._settings.db_path).expanduser())
        database = Database(db_path)
        try:
            database.initialize()
            database.migrate()
            result = database.maintain(auto_vacuum=self._settings.auto_vacuum)
        finally:
            database.close()

        result["backup_path"] = None
        if include_backup and self._settings.backup_enabled:
            backup_dir = Path(self._settings.backup_dir).expanduser()
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
            backup_path = backup_dir / f"cogito_{timestamp}.zip"
            create_backup(
                str(backup_path),
                db_path=db_path,
                include_secrets=False,
                data_dir=str(Path(db_path).parent),
            )
            result["backup_path"] = str(backup_path)
            result["backups_removed"] = self._enforce_retention(backup_dir)
        return result

    def run(self) -> None:
        maintenance_seconds = max(60, self._settings.maintenance_interval_hours * 3600)
        backup_every = max(1, self._settings.backup_interval_hours)
        cycles = 0
        while not self._stop_event.is_set():
            self.run_once(include_backup=cycles % backup_every == 0)
            cycles += max(1, self._settings.maintenance_interval_hours)
            self._stop_event.wait(maintenance_seconds)

    def stop(self) -> None:
        self._stop_event.set()

    def _enforce_retention(self, backup_dir: Path) -> int:
        keep = max(1, self._settings.backup_retention_count)
        backups = sorted(
            backup_dir.glob("cogito_*.zip"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        removed = 0
        for expired in backups[keep:]:
            expired.unlink()
            removed += 1
        return removed
