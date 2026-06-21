from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from cogito_agent.cli.diagnostics import create_diagnostic_bundle
from cogito_agent.storage import Database


def test_diagnostic_bundle_is_redacted_and_has_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "sk-super-secret-value")
    db_path = tmp_path / "cogito.db"
    database = Database(str(db_path))
    database.initialize()
    database.migrate()
    database.close()
    log_path = tmp_path / "cogito.log"
    log_path.write_text("authorization=Bearer hidden-token password=hunter2", encoding="utf-8")
    bundle = tmp_path / "diagnostics.zip"

    report = create_diagnostic_bundle(str(bundle), db_path=str(db_path), log_path=str(log_path))

    assert report["contains_secrets"] is False
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        payload = "\n".join(archive.read(name).decode("utf-8") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
    assert names == {
        "config.redacted.json",
        "database.json",
        "logs.redacted.txt",
        "manifest.json",
        "system.json",
    }
    assert manifest["contains_application_rows"] is False
    assert "sk-super-secret-value" not in payload
    assert "hidden-token" not in payload
    assert "hunter2" not in payload
