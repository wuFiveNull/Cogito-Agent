from __future__ import annotations

import csv
import json
import mimetypes
import os
import uuid
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer
from cogito_agent.trace.redaction import RedactionHelper

from .registry import WorkspaceFileRegistry

TEXT_EXTS: set[str] = {".txt", ".md", ".json", ".py", ".ts", ".js", ".csv"}
MAX_FILE_SIZE: int = 10 * 1024 * 1024
CHUNK_SIZE: int = 1000


class FileIngestionService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._registry = WorkspaceFileRegistry(db)
        self._tracer = Tracer(db)
        self._audit = AuditLogger(db)
        self._redactor = RedactionHelper()

    def scan_root(self, root_id: str, workspace_id: str, trace_id: str = "") -> dict[str, int]:
        root_row = self._registry.get_root_by_id(root_id)
        if root_row is None:
            return {"scanned": 0, "errors": 0, "ignored": 0}

        should_trace = bool(trace_id)
        if should_trace:
            span = self._tracer.create_span(trace_id, "file_scan", SpanKind.tool)
        else:
            trace = self._tracer.create_trace(
                workspace_id=workspace_id,
                root_event_id=f"scan_root_{root_id}",
            )
            span = self._tracer.create_span(trace.id, "file_scan", SpanKind.tool)
            trace_id = trace.id

        counts: dict[str, int] = {"scanned": 0, "errors": 0, "ignored": 0}
        try:
            root_path_str = str(root_row["root_path"])
            root_path = Path(root_path_str).resolve()
            ignore_patterns = str(root_row.get("ignore_patterns", ""))
            max_size = int(str(root_row.get("max_file_size", MAX_FILE_SIZE)))

            if not root_path.is_dir():
                if should_trace:
                    self._tracer.end_span(span)
                return counts

            existing_files: dict[str, dict[str, object]] = {}
            for ef in self._registry.list_files(workspace_id, root_id=root_id):
                existing_files[str(ef["relative_path"])] = ef

            seen: set[str] = set()

            for file_path in root_path.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = os.path.relpath(file_path, root_path)
                rel = rel.replace(os.sep, "/")

                if WorkspaceFileRegistry.matches_ignore_patterns(rel, ignore_patterns):
                    counts["ignored"] += 1
                    continue

                if file_path.stat().st_size > max_size:
                    counts["ignored"] += 1
                    continue

                seen.add(rel)
                ext = file_path.suffix.lower()

                if ext not in TEXT_EXTS:
                    counts["ignored"] += 1
                    continue

                existing = existing_files.get(rel)
                mime_type, _ = mimetypes.guess_type(str(file_path))
                mime_type = mime_type or "text/plain"
                mod_time = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC).isoformat()
                sha256 = WorkspaceFileRegistry.compute_sha256(file_path)
                size = file_path.stat().st_size

                if existing:
                    existing_sha = str(existing.get("sha256", ""))
                    if existing_sha == sha256:
                        counts["scanned"] += 1
                        continue
                    fid = str(existing["id"])
                    self._registry.update_file_indexed(fid, sha256, size, mod_time)
                else:
                    file_rec = self._registry.register_file(
                        workspace_id=workspace_id,
                        root_id=root_id,
                        relative_path=rel,
                        file_name=file_path.name,
                        mime_type=mime_type,
                        size_bytes=size,
                        sha256=sha256,
                        modified_at=mod_time,
                    )
                    fid = str(file_rec["id"])

                try:
                    self._ingest_file(file_path, fid, workspace_id)
                    counts["scanned"] += 1
                except Exception as exc:
                    self._registry.mark_file_error(fid, str(exc))
                    counts["errors"] += 1

            for rel_path, ef in existing_files.items():
                if rel_path not in seen:
                    fid = str(ef["id"])
                    self._registry.update_file_status(fid, "deleted")

            self._audit.log(
                actor_id="system",
                action="workspace.file.scan",
                resource=f"root:{root_id}",
                workspace_id=workspace_id,
                trace_id=trace_id,
                reason=f"Scan complete: {counts}",
                redact_details=True,
            )
        finally:
            self._tracer.end_span(span)
            if not should_trace:
                self._tracer.end_trace(trace)

        return counts

    def _ingest_file(self, file_path: Path, fid: str, workspace_id: str) -> None:
        ext = file_path.suffix.lower()
        text = self._extract_text(file_path, ext)
        redacted = self._redactor.redact(text)

        self._db.connection.execute("DELETE FROM file_chunks WHERE workspace_file_id = ?", (fid,))
        fts_rows = self._db.connection.execute(
            "SELECT rowid FROM file_chunks WHERE workspace_file_id = ?", (fid,)
        )
        for row in fts_rows.fetchall():
            self._db.connection.execute(
                "DELETE FROM file_chunks_fts WHERE rowid = ?", (row["rowid"],)
            )
        self._db.connection.execute(
            "DELETE FROM file_chunk_embeddings"
            " WHERE chunk_id IN (SELECT id FROM file_chunks WHERE workspace_file_id = ?)",
            (fid,),
        )

        lines = redacted.split("\n")
        total_chars = len(redacted)
        chunk_size = min(CHUNK_SIZE, max(500, total_chars // 10))
        chunks: list[dict[str, Any]] = []
        current_chars: list[str] = []
        char_count = 0
        start_line = 0
        current_line = 0

        for line_idx, line in enumerate(lines):
            current_line = line_idx
            current_chars.append(line)
            char_count += len(line) + 1
            if char_count >= chunk_size:
                chunk_text = "\n".join(current_chars)
                chunks.append(
                    {
                        "text": chunk_text,
                        "start_line": start_line,
                        "end_line": current_line,
                    }
                )
                current_chars = []
                char_count = 0
                start_line = current_line + 1

        if current_chars:
            chunk_text = "\n".join(current_chars)
            chunks.append(
                {
                    "text": chunk_text,
                    "start_line": start_line,
                    "end_line": current_line,
                }
            )

        for idx, chunk_data in enumerate(chunks):
            cid = str(uuid.uuid4())
            chunk_text = chunk_data["text"]
            token_count = self._estimate_tokens(chunk_text)
            chunk_sha = WorkspaceFileRegistry.compute_text_sha256(chunk_text)
            self._db.connection.execute(
                "INSERT INTO file_chunks"
                " (id, workspace_file_id, workspace_id, chunk_index, text,"
                " token_count, start_line, end_line, sha256, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    fid,
                    workspace_id,
                    idx,
                    chunk_text,
                    token_count,
                    chunk_data["start_line"],
                    chunk_data["end_line"],
                    chunk_sha,
                    datetime.now(UTC).isoformat(),
                ),
            )
            rowid_cur = self._db.connection.execute(
                "SELECT rowid FROM file_chunks WHERE id = ?", (cid,)
            )
            rowid_row = rowid_cur.fetchone()
            if rowid_row:
                self._db.connection.execute(
                    "INSERT INTO file_chunks_fts(rowid, text) VALUES (?, ?)",
                    (rowid_row["rowid"], chunk_text),
                )

        self._try_create_chunk_embeddings(fid, workspace_id)
        self._db.connection.commit()

    def _extract_text(self, file_path: Path, ext: str) -> str:
        try:
            raw = file_path.read_bytes()
            text = self._decode_with_fallback(raw)
            if ext == ".json":
                parsed = json.loads(text)
                text = json.dumps(parsed, indent=2, ensure_ascii=False)
            elif ext == ".csv":
                reader = csv.reader(StringIO(text))
                rows: list[str] = []
                for row in reader:
                    rows.append("| " + " | ".join(row) + " |")
                text = "\n".join(rows)
            return text
        except Exception as e:
            raise RuntimeError(f"extract failed: {e}") from e

    @staticmethod
    def _decode_with_fallback(raw: bytes) -> str:
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        try:
            from cogito_agent.models import token_count

            return token_count(text)
        except Exception:
            return max(1, len(text) // 4)

    def _try_create_chunk_embeddings(self, fid: str, workspace_id: str) -> None:
        try:
            from cogito_agent.embedding.service import (
                _pack_embedding,
                create_embedding_provider_from_config,
            )
            from cogito_agent.config import Settings

            provider = create_embedding_provider_from_config(Settings.get().memory.embedding)
            if provider is None:
                return
            chunks = self._db.connection.execute(
                "SELECT id, text FROM file_chunks WHERE workspace_file_id = ? ORDER BY chunk_index",
                (fid,),
            ).fetchall()
            for chunk in chunks:
                try:
                    vec = provider.embed_text(str(chunk["text"]))
                    blob = _pack_embedding(vec)
                    self._db.connection.execute(
                        "INSERT OR REPLACE INTO file_chunk_embeddings"
                        " (chunk_id, embedding, model_name) VALUES (?, ?, ?)",
                        (chunk["id"], blob, provider.model_name),
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def reindex_file(self, fid: str, workspace_id: str = "") -> bool:
        row = self._registry.get_file_by_id(fid, workspace_id)
        if row is None:
            return False
        root_id = str(row["root_id"])
        rel = str(row["relative_path"])
        safe = self._registry.resolve_safe_path(root_id, rel)
        if safe is None:
            return False
        ws_id = str(row["workspace_id"])
        try:
            self._ingest_file(safe, fid, ws_id)
            mod_time = datetime.fromtimestamp(safe.stat().st_mtime, tz=UTC).isoformat()
            sha256 = WorkspaceFileRegistry.compute_sha256(safe)
            size = safe.stat().st_size
            self._registry.update_file_indexed(fid, sha256, size, mod_time)

            self._audit.log(
                actor_id="system",
                action="workspace.file.reindex",
                resource=f"file:{fid}",
                workspace_id=ws_id,
                reason=f"Reindexed file: {rel}",
                redact_details=True,
            )
            return True
        except Exception as exc:
            self._registry.mark_file_error(fid, str(exc))
            return False

    def get_file_chunks(
        self,
        fid: str,
        workspace_id: str = "",
    ) -> list[dict[str, object]]:
        sql = "SELECT * FROM file_chunks WHERE workspace_file_id = ?"
        params: list[object] = [fid]
        if workspace_id:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)
        sql += " ORDER BY chunk_index"
        cur = self._db.connection.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def get_chunks_for_context(self, workspace_id: str, limit: int = 5) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT fc.*, wf.file_name, wf.relative_path"
            " FROM file_chunks fc"
            " JOIN workspace_files wf ON wf.id = fc.workspace_file_id"
            " WHERE fc.workspace_id = ? AND wf.status = 'active'"
            " ORDER BY fc.created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
