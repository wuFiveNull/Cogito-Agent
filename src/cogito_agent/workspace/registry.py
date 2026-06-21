from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import _row_to_dict, _rows_to_dicts
from cogito_agent.trace import Tracer


class WorkspaceFileRegistry:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._tracer = Tracer(db)
        self._audit = AuditLogger(db)

    # ── Root Registration ─────────────────────────────────────────────

    def register_root(
        self,
        workspace_id: str,
        root_path: str,
        label: str = "",
        ignore_patterns: str = "",
        max_file_size: int = 10 * 1024 * 1024,
    ) -> dict[str, object]:
        rid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        resolved = self._resolve_absolute(root_path)
        self._db.connection.execute(
            "INSERT INTO workspace_roots"
            " (id, workspace_id, root_path, label, ignore_patterns, max_file_size,"
            " status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (rid, workspace_id, str(resolved), label, ignore_patterns, max_file_size, now, now),
        )
        self._db.connection.commit()

        self._audit.log(
            actor_id="system",
            action="workspace.root.register",
            resource=f"root:{rid}",
            workspace_id=workspace_id,
            reason=f"Registered workspace root: {resolved}",
            redact_details=True,
        )

        result = self.get_root_by_id(rid)
        assert result is not None
        return result

    def get_root_by_id(self, rid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute("SELECT * FROM workspace_roots WHERE id = ?", (rid,))
        return _row_to_dict(cur.fetchone())

    def list_roots(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM workspace_roots WHERE workspace_id = ? ORDER BY created_at",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def delete_root(self, rid: str) -> bool:
        cur = self._db.connection.execute("DELETE FROM workspace_roots WHERE id = ?", (rid,))
        self._db.connection.commit()
        return cur.rowcount > 0

    # ── File Registration ─────────────────────────────────────────────

    def register_file(
        self,
        workspace_id: str,
        root_id: str,
        relative_path: str,
        file_name: str,
        mime_type: str = "",
        size_bytes: int = 0,
        sha256: str = "",
        modified_at: str = "",
    ) -> dict[str, object]:
        fid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT INTO workspace_files"
            " (id, workspace_id, root_id, relative_path, file_name, mime_type,"
            " size_bytes, sha256, modified_at, indexed_at, status, sensitivity_level,"
            " error_message, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'normal', '', ?, ?)",
            (
                fid,
                workspace_id,
                root_id,
                relative_path,
                file_name,
                mime_type,
                size_bytes,
                sha256,
                modified_at,
                now,
                now,
                now,
            ),
        )
        self._db.connection.commit()
        result = self.get_file_by_id(fid)
        assert result is not None
        return result

    def update_file_status(self, fid: str, status: str, error_message: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE workspace_files SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (status, error_message, now, fid),
        )
        self._db.connection.commit()

    def update_file_indexed(self, fid: str, sha256: str, size_bytes: int, modified_at: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE workspace_files SET sha256 = ?, size_bytes = ?,"
            " modified_at = ?, indexed_at = ?, status = 'active', updated_at = ?"
            " WHERE id = ?",
            (sha256, size_bytes, modified_at, now, now, fid),
        )
        self._db.connection.commit()

    def get_file_by_id(
        self,
        fid: str,
        workspace_id: str = "",
    ) -> dict[str, object] | None:
        sql = "SELECT * FROM workspace_files WHERE id = ?"
        params: list[object] = [fid]
        if workspace_id:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)
        cur = self._db.connection.execute(sql, params)
        return _row_to_dict(cur.fetchone())

    def list_files(
        self, workspace_id: str, root_id: str = "", status: str = ""
    ) -> list[dict[str, object]]:
        conditions = ["workspace_id = ?"]
        params: list[object] = [workspace_id]
        if root_id:
            conditions.append("root_id = ?")
            params.append(root_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM workspace_files WHERE " + " AND ".join(conditions)
        sql += " ORDER BY file_name"
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def list_files_by_status(self, workspace_id: str, status: str) -> list[dict[str, object]]:
        return self.list_files(workspace_id, status=status)

    def get_file_by_path(self, workspace_id: str, relative_path: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM workspace_files"
            " WHERE workspace_id = ? AND relative_path = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (workspace_id, relative_path),
        )
        return _row_to_dict(cur.fetchone())

    def remove_file(self, fid: str, workspace_id: str = "") -> bool:
        row = self.get_file_by_id(fid, workspace_id)
        if row is None:
            return False
        ws_id = str(row["workspace_id"])
        self._db.connection.execute(
            "DELETE FROM file_chunk_embeddings"
            " WHERE chunk_id IN (SELECT id FROM file_chunks WHERE workspace_file_id = ?)",
            (fid,),
        )
        fts_chunks = self._db.connection.execute(
            "SELECT rowid FROM file_chunks WHERE workspace_file_id = ?", (fid,)
        )
        for chunk in fts_chunks.fetchall():
            self._db.connection.execute(
                "DELETE FROM file_chunks_fts WHERE rowid = ?", (chunk["rowid"],)
            )
        self._db.connection.execute("DELETE FROM file_chunks WHERE workspace_file_id = ?", (fid,))
        self._db.connection.execute("DELETE FROM workspace_files WHERE id = ?", (fid,))
        self._db.connection.commit()

        self._audit.log(
            actor_id="system",
            action="workspace.file.remove",
            resource=f"file:{fid}",
            workspace_id=ws_id,
            reason=f"Removed file from index: {row.get('relative_path', '')}",
            redact_details=True,
        )
        return True

    def mark_file_error(self, fid: str, error: str) -> None:
        self.update_file_status(fid, "error", error)

    # ── Path Safety ───────────────────────────────────────────────────

    def _resolve_absolute(self, path: str) -> Path:
        return Path(path).resolve()

    def resolve_safe_path(self, root_id: str, relative_path: str) -> Path | None:
        root_row = self.get_root_by_id(root_id)
        if root_row is None:
            return None
        root_path_str = str(root_row["root_path"])
        root_path = Path(root_path_str).resolve()
        if not root_path.is_dir():
            return None

        candidate = (root_path / relative_path).resolve()
        root_str = str(root_path).rstrip("\\/")
        candidate_str = str(candidate).rstrip("\\/")

        if os.name == "nt":
            if not candidate_str.lower().startswith(root_str.lower()):
                return None
        else:
            if not candidate_str.startswith(root_str):
                return None

        if not candidate.exists():
            return None

        try:
            real = candidate.resolve()
            if os.name == "nt":
                if not str(real).lower().startswith(root_str.lower()):
                    return None
            else:
                if not str(real).startswith(root_str):
                    return None
        except (OSError, ValueError):
            return None

        return candidate

    def get_file_path(self, fid: str) -> Path | None:
        row = self.get_file_by_id(fid)
        if row is None:
            return None
        root_id = str(row["root_id"])
        rel_path = str(row["relative_path"])
        return self.resolve_safe_path(root_id, rel_path)

    # ── File hashing ──────────────────────────────────────────────────

    @staticmethod
    def compute_sha256(file_path: Path) -> str:
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def compute_text_sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # ── Ignore patterns ───────────────────────────────────────────────

    @staticmethod
    def matches_ignore_patterns(relative_path: str, patterns: str) -> bool:
        if not patterns:
            return False
        import fnmatch

        normalized = relative_path.replace("\\", "/")
        segments = normalized.split("/")
        for pattern in patterns.split("\n"):
            p = pattern.strip()
            if not p or p.startswith("#"):
                continue
            if fnmatch.fnmatch(normalized, p):
                return True
            if fnmatch.fnmatch(segments[-1], p):
                return True
            for seg in segments[:-1]:
                if fnmatch.fnmatch(seg, p):
                    return True
            if fnmatch.fnmatch(normalized, "*/" + p):
                return True
            if fnmatch.fnmatch(normalized, "**/" + p):
                return True
        return False
