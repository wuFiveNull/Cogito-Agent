from __future__ import annotations

import os
from pathlib import Path

from cogito_agent.cli.maintenance import MaintenanceWorker
from cogito_agent.config import StorageSettings
from cogito_agent.storage import Database


def _settings(tmp_path: Path, *, retention: int = 2) -> StorageSettings:
    db_path = tmp_path / "cogito.db"
    db = Database(str(db_path))
    db.initialize()
    db.migrate()
    db.close()
    return StorageSettings(
        db_path=str(db_path),
        backup_dir=str(tmp_path / "backups"),
        backup_retention_count=retention,
    )


def test_maintenance_worker_runs_check_and_backup(tmp_path: Path) -> None:
    worker = MaintenanceWorker(_settings(tmp_path))

    result = worker.run_once()

    assert result["integrity_ok"] is True
    assert result["optimized"] is True
    assert Path(result["backup_path"]).is_file()


def test_maintenance_worker_can_skip_backup(tmp_path: Path) -> None:
    worker = MaintenanceWorker(_settings(tmp_path))

    result = worker.run_once(include_backup=False)

    assert result["backup_path"] is None


def test_maintenance_worker_enforces_retention(tmp_path: Path) -> None:
    settings = _settings(tmp_path, retention=2)
    worker = MaintenanceWorker(settings)
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    for index in range(3):
        path = backup_dir / f"cogito_old_{index}.zip"
        path.write_bytes(b"old")
        os.utime(path, (index + 1, index + 1))

    removed = worker._enforce_retention(backup_dir)

    assert removed == 1
    assert len(list(backup_dir.glob("cogito_*.zip"))) == 2
