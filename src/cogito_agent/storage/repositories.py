from __future__ import annotations

import sqlite3
import uuid

from .database import Database


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    return [dict(r) for r in rows]


class WorkspaceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, wid: str, name: str) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO workspaces (id, name) VALUES (?, ?)",
            (wid, name),
        )
        self._db.connection.commit()
        result = self.get_by_id(wid)
        assert result is not None
        return result

    def get_by_id(self, wid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM workspaces WHERE id = ? AND deleted_at IS NULL",
            (wid,),
        )
        return _row_to_dict(cur.fetchone())

    def list_all(self) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM workspaces WHERE deleted_at IS NULL",
        )
        return _rows_to_dicts(cur.fetchall())

    def soft_delete(self, wid: str) -> None:
        self._db.connection.execute(
            "UPDATE workspaces SET deleted_at = datetime('now') WHERE id = ?",
            (wid,),
        )
        self._db.connection.commit()

    def hard_delete(self, wid: str) -> bool:
        cur = self._db.connection.execute(
            "SELECT id FROM workspaces WHERE id = ?", (wid,)
        )
        if cur.fetchone() is None:
            return False
        tables = [
            "notifications", "scheduled_jobs", "approval_records",
            "workspace_settings", "context_items", "source_lineage",
            "audit_logs", "model_calls", "tool_calls", "spans", "traces",
            "workspace_skills", "skill_run_logs",
            "memory_candidates", "file_artifacts",
        ]
        msgs = self._db.connection.execute(
            "SELECT id FROM messages WHERE workspace_id = ?", (wid,)
        )
        for row in msgs.fetchall():
            self._db.connection.execute(
                "DELETE FROM source_lineage WHERE source_id = ?", (row["id"],)
            )
        self._db.connection.execute(
            "DELETE FROM messages WHERE workspace_id = ?", (wid,)
        )
        sessions = self._db.connection.execute(
            "SELECT id FROM sessions WHERE workspace_id = ?", (wid,)
        )
        for row in sessions.fetchall():
            sid = row["id"]
            self._db.connection.execute(
                "DELETE FROM source_lineage WHERE trace_id IN"
                " (SELECT id FROM traces WHERE session_id = ?)", (sid,)
            )
            self._db.connection.execute(
                "DELETE FROM traces WHERE session_id = ?", (sid,)
            )
        self._db.connection.execute(
            "DELETE FROM sessions WHERE workspace_id = ?", (wid,)
        )
        memories = self._db.connection.execute(
            "SELECT id FROM memories WHERE workspace_id = ?", (wid,)
        )
        for row in memories.fetchall():
            mid = row["id"]
            self._db.connection.execute(
                "DELETE FROM memory_embeddings WHERE memory_id = ?", (mid,)
            )
            cur2 = self._db.connection.execute(
                "SELECT rowid FROM memories WHERE id = ?", (mid,)
            )
            r = cur2.fetchone()
            if r:
                self._db.connection.execute(
                    "DELETE FROM memories_fts WHERE rowid = ?", (r["rowid"],)
                )
        self._db.connection.execute(
            "DELETE FROM memories WHERE workspace_id = ?", (wid,)
        )
        for table in tables:
            try:
                self._db.connection.execute(
                    f"DELETE FROM {table} WHERE workspace_id = ?", (wid,)  # noqa: S608
                )
            except Exception:
                pass
        self._db.connection.execute(
            "DELETE FROM workspaces WHERE id = ?", (wid,)
        )
        self._db.connection.commit()
        return True


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, sid: str, workspace_id: str, title: str = ""
    ) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO sessions (id, workspace_id, title) VALUES (?, ?, ?)",
            (sid, workspace_id, title),
        )
        self._db.connection.commit()
        result = self.get_by_id(sid, workspace_id)
        assert result is not None
        return result

    def get_by_id(
        self, sid: str, workspace_id: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM sessions WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (sid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_workspace(
        self, workspace_id: str
    ) -> list[dict[str, object]]:
        sql = (
            "SELECT * FROM sessions WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY updated_at DESC"
        )
        cur = self._db.connection.execute(sql, (workspace_id,))
        return _rows_to_dicts(cur.fetchall())

    def soft_delete(self, sid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE sessions SET deleted_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ?",
            (sid, workspace_id),
        )
        self._db.connection.commit()

    def hard_delete(self, sid: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "SELECT id FROM sessions WHERE id = ? AND workspace_id = ?",
            (sid, workspace_id),
        )
        if cur.fetchone() is None:
            return False
        self._db.connection.execute(
            "DELETE FROM messages WHERE session_id = ? AND workspace_id = ?",
            (sid, workspace_id),
        )
        self._db.connection.execute(
            "DELETE FROM traces WHERE session_id = ?", (sid,)
        )
        self._db.connection.execute(
            "DELETE FROM source_lineage WHERE trace_id IN"
            " (SELECT id FROM traces WHERE session_id = ?)", (sid,)
        )
        self._db.connection.execute(
            "DELETE FROM sessions WHERE id = ? AND workspace_id = ?",
            (sid, workspace_id),
        )
        self._db.connection.commit()
        return True


class MessageRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        mid: str,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str = "",
        metadata_json: str = "{}",
    ) -> dict[str, object]:
        sql = (
            "INSERT INTO messages"
            " (id, workspace_id, session_id, role, content, metadata_json)"
            " VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._db.connection.execute(
            sql,
            (mid, workspace_id, session_id, role, content, metadata_json),
        )
        self._db.connection.commit()
        result = self.get_by_id(mid, workspace_id)
        assert result is not None
        return result

    def get_by_id(
        self, mid: str, workspace_id: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM messages WHERE id = ?"
            " AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_session(
        self, session_id: str, workspace_id: str
    ) -> list[dict[str, object]]:
        sql = (
            "SELECT * FROM messages WHERE session_id = ?"
            " AND workspace_id = ? AND deleted_at IS NULL"
            " ORDER BY created_at ASC"
        )
        cur = self._db.connection.execute(sql, (session_id, workspace_id))
        return _rows_to_dicts(cur.fetchall())

    def soft_delete_by_session(self, session_id: str, workspace_id: str) -> None:
        sql = (
            "UPDATE messages SET deleted_at = datetime('now')"
            " WHERE session_id = ? AND workspace_id = ?"
        )
        self._db.connection.execute(sql, (session_id, workspace_id))
        self._db.connection.commit()

    def hard_delete_by_session(
        self, session_id: str, workspace_id: str
    ) -> int:
        cur = self._db.connection.execute(
            "DELETE FROM messages WHERE session_id = ? AND workspace_id = ?",
            (session_id, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount


class MemoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, mid: str, workspace_id: str, text: str, type: str = "general"
    ) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO memories (id, workspace_id, text, type) VALUES (?, ?, ?, ?)",
            (mid, workspace_id, text, type),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (mid,)
        )
        row = cur.fetchone()
        if row:
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (row["rowid"], text, ""),
            )
            self._db.connection.commit()
        self._try_create_embedding(mid, text)
        result = self.get_by_id(mid, workspace_id)
        assert result is not None
        return result

    def _try_create_embedding(self, mid: str, text: str) -> None:
        try:
            from cogito_agent.memory.vector import EmbeddingService, _pack_embedding
            svc = EmbeddingService()
            vec = svc.encode(text)
            blob = _pack_embedding(vec)
            self._db.connection.execute(
                "INSERT OR REPLACE INTO memory_embeddings"
                " (memory_id, embedding, model_name)"
                " VALUES (?, ?, ?)",
                (mid, blob, svc.model_name),
            )
            self._db.connection.commit()
        except Exception:
            pass

    def backfill_embeddings(self) -> int:
        count = 0
        try:
            cur = self._db.connection.execute(
                "SELECT id, text FROM memories WHERE deleted_at IS NULL"
            )
            for row in cur.fetchall():
                mid, text = row["id"], row["text"]
                existing = self._db.connection.execute(
                    "SELECT 1 FROM memory_embeddings WHERE memory_id = ?", (mid,)
                )
                if existing.fetchone() is None:
                    self._try_create_embedding(mid, text)
                    count += 1
        except Exception:
            pass
        return count

    def get_by_id(
        self, mid: str, workspace_id: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ?"
            " AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_workspace(
        self, workspace_id: str
    ) -> list[dict[str, object]]:
        sql = (
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY created_at DESC"
        )
        cur = self._db.connection.execute(sql, (workspace_id,))
        return _rows_to_dicts(cur.fetchall())

    def pin(self, mid: str, workspace_id: str) -> bool:
        from datetime import UTC, datetime
        cur = self._db.connection.execute(
            "UPDATE memories SET pinned_at = ?"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (datetime.now(UTC).isoformat(), mid, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def archive(self, mid: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "UPDATE memories SET archived_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def soft_delete(self, mid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE memories SET deleted_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        cur = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (mid,)
        )
        row = cur.fetchone()
        if row:
            self._db.connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?",
                (row["rowid"],),
            )
        self._db.connection.execute(
            "DELETE FROM memory_embeddings WHERE memory_id = ?", (mid,)
        )
        self._db.connection.commit()

    def unarchive(self, mid: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "UPDATE memories SET archived_at = NULL"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def unpin(self, mid: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "UPDATE memories SET pinned_at = NULL"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def merge(self, source_mid: str, target_mid: str, workspace_id: str) -> bool:
        cur_src = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (source_mid, workspace_id),
        )
        source = cur_src.fetchone()
        if source is None:
            return False
        cur_tgt = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (target_mid, workspace_id),
        )
        target = cur_tgt.fetchone()
        if target is None:
            return False
        source_text = str(source["text"])
        target_text = str(target["text"])
        merged_text = target_text + "\n\n---\n\n" + source_text
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ?",
            (merged_text, target_mid),
        )
        cur_ft = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (target_mid,)
        )
        row_ft = cur_ft.fetchone()
        if row_ft:
            rowid = row_ft["rowid"]
            self._db.connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?", (rowid,)
            )
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (rowid, merged_text, str(target["summary"] or "")),
            )
        self._db.connection.execute(
            "UPDATE memories SET archived_at = datetime('now'),"
            " source_id = ?, updated_at = datetime('now')"
            " WHERE id = ?",
            (target_mid, source_mid),
        )
        cur_sf = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (source_mid,)
        )
        row_sf = cur_sf.fetchone()
        if row_sf:
            self._db.connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?", (row_sf["rowid"],)
            )
        self._db.connection.execute(
            "DELETE FROM memory_embeddings WHERE memory_id = ?", (source_mid,)
        )
        log_id1 = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_edit_log"
            " (id, memory_id, workspace_id, old_text, new_text, operation, actor_id)"
            " VALUES (?, ?, ?, ?, ?, 'merge_source_archived', ?)",
            (log_id1, source_mid, workspace_id, source_text, merged_text, "cli"),
        )
        log_id2 = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_edit_log"
            " (id, memory_id, workspace_id, old_text, new_text, operation, actor_id)"
            " VALUES (?, ?, ?, ?, ?, 'merge_target_updated', ?)",
            (log_id2, target_mid, workspace_id, target_text, merged_text, "cli"),
        )
        self._db.connection.commit()
        return True

    def edit_text(self, mid: str, workspace_id: str, new_text: str, actor_id: str = "cli") -> bool:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        old = cur.fetchone()
        if old is None:
            return False
        old_text = str(old["text"])
        if old_text == new_text:
            return True
        version_id = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memories"
            " (id, workspace_id, type, status, text, summary,"
            " confidence, sensitivity, source_id, created_at, updated_at)"
            " VALUES (?, ?, ?, 'stale', ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (version_id, workspace_id, str(old["type"]), old_text, str(old["summary"] or ""),
             float(old["confidence"] or 0.5), str(old["sensitivity"] or "normal"), mid),
        )
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (new_text, mid, workspace_id),
        )
        cur_ft = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (mid,)
        )
        row = cur_ft.fetchone()
        if row:
            rowid = row["rowid"]
            self._db.connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?", (rowid,)
            )
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (rowid, new_text, str(old["summary"] or "")),
            )
        self._db.connection.execute(
            "DELETE FROM memory_embeddings WHERE memory_id = ?", (mid,)
        )
        log_id = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_edit_log"
            " (id, memory_id, workspace_id, old_text, new_text, operation, actor_id)"
            " VALUES (?, ?, ?, ?, ?, 'edit', ?)",
            (log_id, mid, workspace_id, old_text, new_text, actor_id),
        )
        self._db.connection.commit()
        return True

    def correct_text(
        self, mid: str, workspace_id: str, new_text: str, actor_id: str = "cli",
    ) -> bool:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        old = cur.fetchone()
        if old is None:
            return False
        old_text = str(old["text"])
        if old_text == new_text:
            return True
        version_id = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memories"
            " (id, workspace_id, type, status, text, summary,"
            " confidence, sensitivity, source_id, created_at, updated_at)"
            " VALUES (?, ?, ?, 'stale', ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (version_id, workspace_id, str(old["type"]), old_text, str(old["summary"] or ""),
             float(old["confidence"] or 0.5), str(old["sensitivity"] or "normal"), mid),
        )
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (new_text, mid, workspace_id),
        )
        cur_ft = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (mid,)
        )
        row = cur_ft.fetchone()
        if row:
            rowid = row["rowid"]
            self._db.connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?", (rowid,)
            )
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (rowid, new_text, str(old["summary"] or "")),
            )
        self._db.connection.execute(
            "DELETE FROM memory_embeddings WHERE memory_id = ?", (mid,)
        )
        log_id = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_edit_log"
            " (id, memory_id, workspace_id, old_text, new_text, operation, actor_id)"
            " VALUES (?, ?, ?, ?, ?, 'correct', ?)",
            (log_id, mid, workspace_id, old_text, new_text, actor_id),
        )
        self._db.connection.commit()
        return True

    def get_by_id_including_deleted(self, mid: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_all_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())


class MemoryCandidateRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        workspace_id: str,
        text: str,
        type: str = "general",
        reason: str = "",
        confidence: float = 0.5,
        session_id: str = "",
        source_message_id: str = "",
    ) -> dict[str, object]:
        import uuid

        cid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO memory_candidates"
            " (id, workspace_id, session_id, text, type, reason, confidence, source_message_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, workspace_id, session_id, text, type, reason, confidence, source_message_id),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        return dict(cur.fetchone())

    def accept(self, cid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        row = cur.fetchone()
        if not row:
            return None
        cand = dict(row)
        self._db.connection.execute(
            "UPDATE memory_candidates SET status = 'accepted' WHERE id = ?", (cid,)
        )
        mem_repo = MemoryRepository(self._db)
        mem_repo.create(
            mid=str(uuid.uuid4()),
            workspace_id=cand["workspace_id"],
            text=cand["text"],
            type=cand["type"],
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        return dict(cur.fetchone())

    def reject(self, cid: str) -> dict[str, object] | None:
        self._db.connection.execute(
            "UPDATE memory_candidates SET status = 'rejected' WHERE id = ?", (cid,)
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        result = cur.fetchone()
        return dict(result) if result else None

    def get_by_id(self, cid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE id = ?", (cid,)
        )
        return _row_to_dict(cur.fetchone())

    def list_pending(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_candidates WHERE workspace_id = ?"
            " AND status = 'pending' ORDER BY created_at DESC",
            (workspace_id,),
        )
        return [dict(r) for r in cur.fetchall()]


class FileArtifactRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        fid: str,
        workspace_id: str,
        path: str,
        mime_type: str = "",
        sha256: str = "",
    ) -> dict[str, object]:
        sql = (
            "INSERT INTO file_artifacts"
            " (id, workspace_id, path, mime_type, sha256)"
            " VALUES (?, ?, ?, ?, ?)"
        )
        self._db.connection.execute(
            sql, (fid, workspace_id, path, mime_type, sha256),
        )
        self._db.connection.commit()
        result = self.get_by_id(fid, workspace_id)
        assert result is not None
        return result

    def get_by_id(
        self, fid: str, workspace_id: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM file_artifacts WHERE id = ?"
            " AND workspace_id = ? AND deleted_at IS NULL",
            (fid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_workspace(
        self, workspace_id: str
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM file_artifacts WHERE workspace_id = ?"
            " AND deleted_at IS NULL",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def soft_delete(self, fid: str, workspace_id: str) -> None:
        sql = (
            "UPDATE file_artifacts SET deleted_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ?"
        )
        self._db.connection.execute(sql, (fid, workspace_id))
        self._db.connection.commit()

    def hard_delete(self, fid: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "DELETE FROM file_artifacts WHERE id = ? AND workspace_id = ?",
            (fid, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0


class MemoryEditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def update_text(self, mid: str, workspace_id: str, text: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ?"
            " AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        old = cur.fetchone()
        if old is None:
            return None
        old_text = str(old["text"])
        if old_text != text:
            version_id = str(uuid.uuid4())
            self._db.connection.execute(
                "INSERT INTO memories"
                " (id, workspace_id, type, status, text, summary, confidence,"
                " sensitivity, source_id, created_at, updated_at)"
                " VALUES (?, ?, ?, 'stale', ?, ?, ?, ?, ?,"
                " datetime('now'), datetime('now'))",
                (
                    version_id, workspace_id, old["type"],
                    old_text, old["summary"],
                    old["confidence"], old["sensitivity"],
                    mid,
                ),
            )
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (text, mid, workspace_id),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ?", (mid,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def hard_delete(self, mid: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        row = cur.fetchone()
        if row is None:
            return False
        rowid = row["rowid"]
        self._db.connection.execute(
            "DELETE FROM memories_fts WHERE rowid = ?", (rowid,)
        )
        self._db.connection.execute(
            "DELETE FROM memory_embeddings WHERE memory_id = ?", (mid,)
        )
        self._db.connection.execute(
            "DELETE FROM memories WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        self._db.connection.commit()
        return True

    def list_by_type(
        self, workspace_id: str, memory_type: str, limit: int = 50
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND type = ? AND deleted_at IS NULL"
            " ORDER BY created_at DESC LIMIT ?",
            (workspace_id, memory_type, limit),
        )
        return _rows_to_dicts(cur.fetchall())


class ApprovalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        workspace_id: str,
        actor_id: str,
        capability_name: str,
        operation: str = "",
        resource: str = "",
        reason: str = "",
        session_id: str = "",
    ) -> dict[str, object]:
        aid = str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO approval_records"
            " (id, workspace_id, session_id, actor_id, capability_name,"
            " operation, resource, reason, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (aid, workspace_id, session_id, actor_id, capability_name,
             operation, resource, reason),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records WHERE id = ?", (aid,)
        )
        return dict(cur.fetchone())

    def get_by_id(self, aid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records WHERE id = ?", (aid,)
        )
        return _row_to_dict(cur.fetchone())

    def resolve(
        self, aid: str, decision: str, decided_by: str = ""
    ) -> dict[str, object] | None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        cur = self._db.connection.execute(
            "UPDATE approval_records"
            " SET status = ?, decision = ?, decided_by = ?, decided_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (decision, decision, decided_by, now, aid),
        )
        self._db.connection.commit()
        if cur.rowcount == 0:
            return None
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records WHERE id = ?", (aid,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_pending(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records"
            " WHERE workspace_id = ? AND status = 'pending'"
            " ORDER BY created_at DESC",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_workspace(
        self, workspace_id: str, limit: int = 50
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records"
            " WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return _rows_to_dicts(cur.fetchall())


class WorkspaceSettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, workspace_id: str) -> dict[str, object]:
        cur = self._db.connection.execute(
            "SELECT * FROM workspace_settings WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        return {"workspace_id": workspace_id, "quiet_hours_start": "",
                "quiet_hours_end": "", "timezone": "UTC",
                "max_daily_notifications": 3}

    def upsert(self, workspace_id: str, **kwargs: str | int) -> dict[str, object]:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        values = list(kwargs.values())
        self._db.connection.execute(
            "INSERT INTO workspace_settings (workspace_id, quiet_hours_start,"
            " quiet_hours_end, timezone, max_daily_notifications)"
            " VALUES (?, '', '', 'UTC', 3)"
            " ON CONFLICT(workspace_id) DO NOTHING",
            (workspace_id,),
        )
        if cols:
            self._db.connection.execute(
                f"UPDATE workspace_settings SET ({cols}) = ({placeholders})"
                f" WHERE workspace_id = ?",
                [*values, workspace_id],
            )
        self._db.connection.commit()
        return self.get(workspace_id)
