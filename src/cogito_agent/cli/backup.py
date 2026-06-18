from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _get_default_data_dir() -> str:
    return str(Path.home() / ".cogito")


def _redact_db(db_path: str, out_path: str) -> None:
    """Copy a SQLite database and redact secret values."""
    shutil.copy2(db_path, out_path)
    try:
        conn = sqlite3.connect(out_path)
        try:
            conn.execute("DELETE FROM secrets")
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception:
        pass


def create_backup(
    out_path: str,
    db_path: str = "",
    include_secrets: bool = False,
    data_dir: str = "",
) -> dict[str, Any]:
    """Create a full system backup as a ZIP archive.

    Includes: SQLite DB, memory embeddings, workspace metadata,
    skill copies, config snapshot, audit/trace logs.

    Secrets are excluded by default (use ``--include-secrets``).
    """
    if not data_dir:
        data_dir = _get_default_data_dir()
    if not db_path:
        db_path = os.path.join(data_dir, "cogito.db")
    if not out_path:
        now = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(data_dir, f"backup_{now}.zip")

    manifest: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "version": "0.11.0-dev",
        "tool": "cogito backup create",
        "include_secrets": include_secrets,
        "files": [],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. SQLite DB (redacted if no --include-secrets)
        db_target = tmp / "cogito.db"
        if include_secrets:
            shutil.copy2(db_path, str(db_target))
        else:
            _redact_db(db_path, str(db_target))
        manifest["files"].append("cogito.db")

        # 2. Config snapshot
        config_path = Path(data_dir) / "config.json"
        config_target = tmp / "config.json"
        if config_path.exists():
            try:
                cfg_data = json.loads(config_path.read_text(encoding="utf-8"))
                if not include_secrets:
                    for k in list(cfg_data.keys()):
                        if any(secret_kw in k.lower() for secret_kw in
                               ("api_key", "secret", "password", "token", "bearer")):
                            cfg_data[k] = "[REDACTED]"
                config_target.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
                manifest["files"].append("config.json")
            except Exception:
                pass

        # 3. Skills
        skills_dir = Path(data_dir) / "skills"
        skills_target = tmp / "skills"
        if skills_dir.is_dir():
            shutil.copytree(str(skills_dir), str(skills_target), dirs_exist_ok=True)
            manifest["files"].append("skills/")

        # 4. Secret key (only if --include-secrets)
        if include_secrets:
            key_path = Path(data_dir) / "secrets.key"
            if key_path.exists():
                shutil.copy2(str(key_path), str(tmp / "secrets.key"))
                manifest["files"].append("secrets.key")

        # 5. Audit log export
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC"
            ).fetchall()
            audit_data = [dict(r) for r in rows]
            (tmp / "audit_logs.json").write_text(
                json.dumps(audit_data, indent=2, default=str), encoding="utf-8"
            )
            conn.close()
            manifest["files"].append("audit_logs.json")
        except Exception:
            pass

        # 6. Trace log export
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM traces ORDER BY started_at DESC"
            ).fetchall()
            trace_data = [dict(r) for r in rows]
            (tmp / "traces.json").write_text(
                json.dumps(trace_data, indent=2, default=str), encoding="utf-8"
            )
            conn.close()
            manifest["files"].append("traces.json")
        except Exception:
            pass

        # 7. Workspace export
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM workspaces").fetchall()
            ws_data = [dict(r) for r in rows]
            (tmp / "workspaces.json").write_text(
                json.dumps(ws_data, indent=2, default=str), encoding="utf-8"
            )
            conn.close()
            manifest["files"].append("workspaces.json")
        except Exception:
            pass

        # Write manifest
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        manifest["files"].append("manifest.json")

        # Create ZIP
        out_path_parent = Path(out_path).parent
        out_path_parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in tmp.rglob("*"):
                arcname = str(f.relative_to(tmp))
                zf.write(str(f), arcname)

    manifest["path"] = out_path
    manifest["size_bytes"] = os.path.getsize(out_path)
    return manifest


def restore_backup(
    backup_path: str,
    db_path: str = "",
    dry_run: bool = False,
    data_dir: str = "",
) -> dict[str, Any]:
    """Restore a backup from a ZIP archive.

    Returns a preflight report when ``dry_run=True``.
    """
    if not data_dir:
        data_dir = _get_default_data_dir()
    if not db_path:
        db_path = os.path.join(data_dir, "cogito.db")

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "files_found": [],
        "actions": [],
        "warnings": [],
        "errors": [],
    }

    if not os.path.isfile(backup_path):
        result["errors"].append(f"Backup file not found: {backup_path}")
        return result

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(backup_path, "r") as zf:
            zf.extractall(str(tmp))

        # Read manifest
        manifest_path = tmp / "manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        result["manifest"] = manifest
        result["files_found"] = list(manifest.get("files", []))

        if dry_run:
            result["actions"].append(f"Would restore SQLite DB to {db_path}")
            result["actions"].append(f"Would restore config to {data_dir}/config.json")
            result["actions"].append("Would restore skills to {data_dir}/skills/")
            if "audit_logs.json" in manifest.get("files", []):
                result["actions"].append("Would import audit logs")
            if "traces.json" in manifest.get("files", []):
                result["actions"].append("Would import trace logs")
            if not manifest.get("include_secrets"):
                result["warnings"].append(
                    "Backup was created WITHOUT secrets. Secrets will NOT be restored."
                )
            return result

        # Perform restore
        db_target = tmp / "cogito.db"
        if db_target.exists():
            shutil.copy2(str(db_target), db_path)
            result["actions"].append(f"Restored SQLite DB to {db_path}")

        config_target = tmp / "config.json"
        if config_target.exists():
            shutil.copy2(str(config_target), os.path.join(data_dir, "config.json"))
            result["actions"].append(f"Restored config to {data_dir}/config.json")

        skills_target = tmp / "skills"
        if skills_target.is_dir():
            skills_dst = Path(data_dir) / "skills"
            skills_dst.mkdir(parents=True, exist_ok=True)
            for f in skills_target.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(skills_target)
                    dst = skills_dst / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(f), str(dst))
            result["actions"].append(f"Restored skills to {data_dir}/skills/")

        if not manifest.get("include_secrets"):
            result["warnings"].append(
                "Secrets were NOT included in the backup. "
                "Use --include-secrets on backup. Re-set secrets manually."
            )

    return result


def export_data(
    out_path: str,
    db_path: str = "",
    sections: list[str] | None = None,
    data_dir: str = "",
) -> dict[str, Any]:
    """Export specific data sections to a JSON file.

    Sections: 'memories', 'traces', 'audit', 'messages', 'config'
    """
    if not data_dir:
        data_dir = _get_default_data_dir()
    if not db_path:
        db_path = os.path.join(data_dir, "cogito.db")
    sections = sections or ["memories"]

    export: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "version": "0.11.0-dev",
        "sections": {},
    }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if "memories" in sections:
        try:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC"
            ).fetchall()
            export["sections"]["memories"] = [dict(r) for r in rows]
        except Exception:
            export["sections"]["memories"] = []

    if "traces" in sections:
        try:
            rows = conn.execute(
                "SELECT * FROM traces ORDER BY started_at DESC"
            ).fetchall()
            export["sections"]["traces"] = [dict(r) for r in rows]
        except Exception:
            export["sections"]["traces"] = []

    if "audit" in sections:
        try:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC"
            ).fetchall()
            export["sections"]["audit"] = [dict(r) for r in rows]
        except Exception:
            export["sections"]["audit"] = []

    if "messages" in sections:
        try:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY created_at DESC"
            ).fetchall()
            export["sections"]["messages"] = [dict(r) for r in rows]
        except Exception:
            export["sections"]["messages"] = []

    if "config" in sections:
        config_path = Path(data_dir) / "config.json"
        if config_path.exists():
            try:
                export["sections"]["config"] = json.loads(
                    config_path.read_text(encoding="utf-8")
                )
            except Exception:
                export["sections"]["config"] = {}

    conn.close()

    out_path_parent = Path(out_path).parent
    out_path_parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, default=str)

    return export
