from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from cogito_agent.cli.backup import create_backup, restore_backup
from cogito_agent.storage import Database


def _create_database(path: Path, value: str) -> None:
    db = Database(str(path))
    db.initialize()
    db.migrate()
    db.connection.execute("CREATE TABLE backup_marker (value TEXT NOT NULL)")
    db.connection.execute("INSERT INTO backup_marker (value) VALUES (?)", (value,))
    db.connection.commit()
    db.close()


def _read_marker(path: Path) -> str:
    conn = sqlite3.connect(path)
    value = str(conn.execute("SELECT value FROM backup_marker").fetchone()[0])
    conn.close()
    return value


def test_backup_restore_roundtrip_and_safety_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    archive = tmp_path / "backup.zip"
    _create_database(source, "from-backup")
    _create_database(destination, "before-restore")

    manifest = create_backup(str(archive), str(source), data_dir=str(tmp_path))
    result = restore_backup(str(archive), str(destination), data_dir=str(tmp_path))

    assert manifest["checksums"]["cogito.db"]
    assert result["errors"] == []
    assert _read_marker(destination) == "from-backup"
    safety_copies = list(tmp_path.glob("destination.db.pre-restore.*.bak"))
    assert len(safety_copies) == 1
    assert _read_marker(safety_copies[0]) == "before-restore"


def test_restore_dry_run_performs_integrity_preflight(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    archive = tmp_path / "backup.zip"
    _create_database(source, "valid")
    create_backup(str(archive), str(source), data_dir=str(tmp_path))

    result = restore_backup(
        str(archive),
        str(tmp_path / "restored.db"),
        dry_run=True,
        data_dir=str(tmp_path),
    )

    assert result["errors"] == []
    assert any("Would restore SQLite DB" in action for action in result["actions"])


def test_restore_rejects_zip_slip_archive(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside.txt", "unsafe")

    result = restore_backup(str(archive), data_dir=str(tmp_path))

    assert result["errors"]
    assert "Unsafe backup member path" in result["errors"][0]
    assert not (tmp_path.parent / "outside.txt").exists()
