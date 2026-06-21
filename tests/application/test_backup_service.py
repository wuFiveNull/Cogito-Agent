from __future__ import annotations

from pathlib import Path

import pytest

from cogito_agent.application import BackupApplicationService
from cogito_agent.storage import Database


def test_backup_service_create_and_preflight(tmp_path: Path) -> None:
    db_path = tmp_path / "cogito.db"
    db = Database(str(db_path))
    db.initialize()
    db.migrate()
    service = BackupApplicationService(
        db_path=str(db_path),
        backup_dir=str(tmp_path / "backups"),
    )
    created = service.create(workspace_id="default")
    name = Path(str(created["path"])).name
    report = service.preflight(name)
    assert report["errors"] == []
    assert report["dry_run"] is True
    db.close()


def test_backup_service_rejects_path_escape(tmp_path: Path) -> None:
    service = BackupApplicationService(
        db_path=str(tmp_path / "cogito.db"),
        backup_dir=str(tmp_path / "backups"),
    )
    with pytest.raises(ValueError, match="Invalid backup filename"):
        service.preflight("../outside.zip")


def test_backup_service_requires_exact_restore_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "cogito.db"
    db = Database(str(db_path))
    db.initialize()
    service = BackupApplicationService(
        db_path=str(db_path),
        backup_dir=str(tmp_path / "backups"),
    )
    created = service.create(workspace_id="default")
    name = Path(str(created["path"])).name
    with pytest.raises(ValueError, match="exactly match"):
        service.restore(
            name,
            confirmation="wrong.zip",
            workspace_id="default",
        )
    db.close()


def test_backup_service_restores_and_calls_completion_hook(tmp_path: Path) -> None:
    db_path = tmp_path / "cogito.db"
    db = Database(str(db_path))
    db.initialize()
    db.migrate()
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES ('before', 'Before')")
    db.connection.commit()
    completed: list[tuple[str, str]] = []

    def close_live_database() -> None:
        db.close()

    service = BackupApplicationService(
        db_path=str(db_path),
        backup_dir=str(tmp_path / "backups"),
        reset_before_restore=close_live_database,
        restore_completed=lambda name, workspace: completed.append((name, workspace)),
    )
    created = service.create(workspace_id="default")
    name = Path(str(created["path"])).name

    changed = Database(str(db_path))
    changed.connection.execute("DELETE FROM workspaces WHERE id='before'")
    changed.connection.commit()
    changed.close()
    result = service.restore(name, confirmation=name, workspace_id="default")

    restored = Database(str(db_path))
    row = restored.connection.execute("SELECT name FROM workspaces WHERE id='before'").fetchone()
    assert not result["errors"]
    assert row is not None and row["name"] == "Before"
    assert completed == [(name, "default")]
    restored.close()
