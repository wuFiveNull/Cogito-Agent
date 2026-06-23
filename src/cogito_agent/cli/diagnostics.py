from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cogito_agent.config import load_config
from cogito_agent.storage import Database
from cogito_agent.shared.redaction import RedactionHelper
from cogito_agent.version import APP_VERSION

_SENSITIVE_KEYS = ("secret", "password", "token", "api_key", "bearer", "credential")


def _redact_value(value: Any, redactor: RedactionHelper, key: str = "") -> Any:
    if any(term in key.lower() for term in _SENSITIVE_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_value(child_value, redactor, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, redactor, key) for item in value]
    if isinstance(value, str):
        return redactor.redact(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_diagnostic_bundle(
    out_path: str,
    *,
    db_path: str | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    """Create a local, redacted diagnostic ZIP without application data."""
    config = load_config()
    redactor = RedactionHelper()
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_json(
            root / "system.json",
            {
                "version": APP_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "python": sys.version,
                "platform": platform.platform(),
                "sqlite": __import__("sqlite3").sqlite_version,
            },
        )
        _write_json(
            root / "config.redacted.json",
            _redact_value(config.model_dump(), redactor),
        )

        database_report: dict[str, Any] = {"configured": bool(db_path)}
        if db_path:
            try:
                database = Database(str(Path(db_path).expanduser()))
                ok, message = database.quick_check()
                database_report.update(
                    {
                        "integrity_ok": ok,
                        "integrity_message": message,
                        "schema_version": database.current_version(),
                    }
                )
                database.close()
            except Exception as exc:
                database_report["error"] = redactor.redact(str(exc))
        _write_json(root / "database.json", database_report)

        if log_path and Path(log_path).is_file():
            lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            (root / "logs.redacted.txt").write_text(
                "\n".join(redactor.redact(line) for line in lines),
                encoding="utf-8",
            )

        files = sorted(item for item in root.iterdir() if item.is_file())
        manifest = {
            "version": APP_VERSION,
            "files": [item.name for item in files],
            "checksums": {item.name: _sha256(item) for item in files},
            "contains_secrets": False,
            "contains_application_rows": False,
        }
        _write_json(root / "manifest.json", manifest)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in root.iterdir():
                if item.is_file():
                    archive.write(item, item.name)

    return {
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        **manifest,
    }
