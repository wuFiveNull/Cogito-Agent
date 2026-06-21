from __future__ import annotations

from pathlib import Path

from cogito_agent.storage import Database


def test_file_database_is_backed_up_before_migration(tmp_path: Path) -> None:
    path = tmp_path / "cogito.db"
    db = Database(str(path))
    db.initialize()

    applied = db.migrate()
    db.close()

    assert applied
    backups = list(tmp_path.glob("cogito.db.pre-migrate.v1-to-v*.bak"))
    assert len(backups) == 1
    backup = Database(str(backups[0]))
    assert backup.current_version() == 1
    backup.close()


def test_database_backup_and_quick_check(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup_path = tmp_path / "backups" / "copy.db"
    db = Database(str(source))
    db.initialize()

    assert db.backup_to(str(backup_path)) == str(backup_path)
    assert db.quick_check() == (True, "ok")
    db.close()

    backup = Database(str(backup_path))
    assert backup.quick_check() == (True, "ok")
    backup.close()


def test_database_maintenance_runs_safe_operations(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "cogito.db"))
    db.initialize()

    result = db.maintain()

    assert result["integrity_ok"] is True
    assert result["optimized"] is True
    assert result["wal_checkpoint"] is not None
    assert result["vacuumed"] is False
    db.close()
