from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cogito_agent.version import APP_VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_copy(source: str, target: str) -> None:
    """Create a transactionally consistent SQLite copy, including WAL state."""
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"Unsafe backup member path: {member.filename}")
        archive.extract(member, destination)


def _check_database(path: Path) -> str | None:
    try:
        conn = sqlite3.connect(str(path))
        result = conn.execute("PRAGMA quick_check").fetchone()
        conn.close()
    except sqlite3.Error as exc:
        return str(exc)
    if result is None or result[0] != "ok":
        return str(result[0] if result else "quick_check returned no result")
    return None


def _get_default_data_dir() -> str:
    return str(Path.home() / ".cogito")


def _redact_db(db_path: str, out_path: str) -> None:
    """Copy a SQLite database and redact secret values."""
    _sqlite_copy(db_path, out_path)
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
        "version": APP_VERSION,
        "tool": "cogito backup create",
        "include_secrets": include_secrets,
        "files": [],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. SQLite DB (redacted if no --include-secrets)
        db_target = tmp / "cogito.db"
        if include_secrets:
            _sqlite_copy(db_path, str(db_target))
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

        manifest["files"].append("manifest.json")
        manifest["checksums"] = {
            str(item.relative_to(tmp)).replace("\\", "/"): _sha256(item)
            for item in tmp.rglob("*")
            if item.is_file()
        }

        # Write manifest after inventory and checksums are final.
        (tmp / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

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
        try:
            with zipfile.ZipFile(backup_path, "r") as zf:
                _safe_extract(zf, tmp)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            result["errors"].append(f"Invalid backup archive: {exc}")
            return result

        # Read manifest
        manifest_path = tmp / "manifest.json"
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        result["manifest"] = manifest
        result["files_found"] = list(manifest.get("files", []))

        checksums = manifest.get("checksums", {})
        if isinstance(checksums, dict):
            for relative_path, expected in checksums.items():
                candidate = tmp / str(relative_path)
                if not candidate.is_file() or _sha256(candidate) != expected:
                    result["errors"].append(
                        f"Checksum mismatch: {relative_path}"
                    )

        db_target = tmp / "cogito.db"
        if db_target.exists():
            db_error = _check_database(db_target)
            if db_error:
                result["errors"].append(f"SQLite integrity check failed: {db_error}")
        else:
            result["errors"].append("Backup does not contain cogito.db")

        if result["errors"]:
            return result

        if dry_run:
            result["actions"].append(f"Would restore SQLite DB to {db_path}")
            result["actions"].append(f"Would restore config to {data_dir}/config.json")
            result["actions"].append(f"Would restore skills to {data_dir}/skills/")
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
        if db_target.exists():
            destination = Path(db_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                safety_copy = destination.with_name(
                    f"{destination.name}.pre-restore.{timestamp}.bak"
                )
                _sqlite_copy(str(destination), str(safety_copy))
                result["actions"].append(
                    f"Created pre-restore safety copy at {safety_copy}"
                )
            _sqlite_copy(str(db_target), str(destination))
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
        "version": APP_VERSION,
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
