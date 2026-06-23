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

    def rename(self, wid: str, name: str) -> bool:
        cursor = self._db.connection.execute(
            "UPDATE workspaces SET name=? WHERE id=? AND deleted_at IS NULL",
            (name, wid),
        )
        self._db.connection.commit()
        return cursor.rowcount == 1

    def soft_delete(self, wid: str) -> None:
        self._db.connection.execute(
            "UPDATE workspaces SET deleted_at = datetime('now') WHERE id = ?",
            (wid,),
        )
        self._db.connection.commit()

    def hard_delete(self, wid: str) -> bool:
        cur = self._db.connection.execute("SELECT id FROM workspaces WHERE id = ?", (wid,))
        if cur.fetchone() is None:
            return False
        tables = [
            "notifications",
            "scheduled_jobs",
            "approval_records",
            "workspace_settings",
            "context_items",
            "source_lineage",
            "audit_logs",
            "model_calls",
            "tool_calls",
            "spans",
            "traces",
            "workspace_skills",
            "skill_run_logs",
            "file_artifacts",
            "file_chunk_embeddings",
            "file_chunks",
            "artifacts",
            "workspace_files",
            "workspace_roots",
            "vision_observations",
            "message_attachments",
            "attachments",
        ]
        msgs = self._db.connection.execute("SELECT id FROM messages WHERE workspace_id = ?", (wid,))
        for row in msgs.fetchall():
            self._db.connection.execute(
                "DELETE FROM source_lineage WHERE source_id = ?", (row["id"],)
            )
        self._db.connection.execute("DELETE FROM messages WHERE workspace_id = ?", (wid,))
        sessions = self._db.connection.execute(
            "SELECT id FROM sessions WHERE workspace_id = ?", (wid,)
        )
        for row in sessions.fetchall():
            sid = row["id"]
            self._db.connection.execute(
                "DELETE FROM source_lineage WHERE trace_id IN"
                " (SELECT id FROM traces WHERE session_id = ?)",
                (sid,),
            )
            self._db.connection.execute("DELETE FROM traces WHERE session_id = ?", (sid,))
        self._db.connection.execute("DELETE FROM sessions WHERE workspace_id = ?", (wid,))
        memories = self._db.connection.execute(
            "SELECT id FROM memories WHERE workspace_id = ?", (wid,)
        )
        for row in memories.fetchall():
            mid = row["id"]
            try:
                self._db.connection.execute(
                    "DELETE FROM memory_embeddings_v2 WHERE memory_id = ?", (mid,)
                )
            except Exception:
                pass
            cur2 = self._db.connection.execute("SELECT rowid FROM memories WHERE id = ?", (mid,))
            r = cur2.fetchone()
            if r:
                self._db.connection.execute(
                    "DELETE FROM memories_fts WHERE rowid = ?", (r["rowid"],)
                )
        self._db.connection.execute("DELETE FROM memories WHERE workspace_id = ?", (wid,))
        for table in tables:
            try:
                self._db.connection.execute(
                    f"DELETE FROM {table} WHERE workspace_id = ?",
                    (wid,),  # noqa: S608
                )
            except Exception:
                pass
        self._db.connection.execute("DELETE FROM workspaces WHERE id = ?", (wid,))
        self._db.connection.commit()
        return True


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, sid: str, workspace_id: str, title: str = "") -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO sessions (id, workspace_id, title) VALUES (?, ?, ?)",
            (sid, workspace_id, title),
        )
        self._db.connection.commit()
        result = self.get_by_id(sid, workspace_id)
        assert result is not None
        return result

    def get_by_id(self, sid: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM sessions WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (sid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        sql = (
            "SELECT * FROM sessions WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY updated_at DESC"
        )
        cur = self._db.connection.execute(sql, (workspace_id,))
        return _rows_to_dicts(cur.fetchall())

    def soft_delete(self, sid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE sessions SET deleted_at = datetime('now') WHERE id = ? AND workspace_id = ?",
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
            "DELETE FROM spans WHERE trace_id IN (SELECT id FROM traces WHERE session_id = ?)",
            (sid,),
        )
        self._db.connection.execute(
            "DELETE FROM source_lineage WHERE trace_id IN"
            " (SELECT id FROM traces WHERE session_id = ?)",
            (sid,),
        )
        self._db.connection.execute("DELETE FROM traces WHERE session_id = ?", (sid,))
        self._db.connection.execute(
            "DELETE FROM sessions WHERE id = ? AND workspace_id = ?",
            (sid, workspace_id),
        )
        self._db.connection.commit()
        return True

    def update(self, sid: str, workspace_id: str, **kwargs: str | None) -> dict[str, object] | None:
        """Update session fields (title, etc.)."""
        if not kwargs:
            return self.get_by_id(sid, workspace_id)
        set_parts = ", ".join(f"{k} = ?" for k in kwargs)
        set_parts += ", updated_at = datetime('now')"
        vals = list(kwargs.values()) + [sid, workspace_id]
        self._db.connection.execute(
            f"UPDATE sessions SET {set_parts}"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            vals,
        )
        self._db.connection.commit()
        return self.get_by_id(sid, workspace_id)

    def restore(self, sid: str, workspace_id: str) -> dict[str, object] | None:
        """Restore a soft-deleted session."""
        self._db.connection.execute(
            "UPDATE sessions SET deleted_at = NULL, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ?",
            (sid, workspace_id),
        )
        self._db.connection.commit()
        return self.get_by_id(sid, workspace_id)

    def hard_delete_by_workspace(self, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "DELETE FROM sessions WHERE workspace_id = ?", (workspace_id,)
        )
        self._db.connection.commit()
        return cur.rowcount

    def cleanup_soft_deleted_before(self, workspace_id: str, cutoff: str) -> int:
        """Hard-delete sessions soft-deleted before the cutoff datetime."""
        cur = self._db.connection.execute(
            "DELETE FROM sessions WHERE workspace_id=? AND deleted_at IS NOT NULL"
            " AND deleted_at < ?",
            (workspace_id, cutoff),
        )
        self._db.connection.commit()
        return cur.rowcount


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

    def get_by_id(self, mid: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM messages WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_session(self, session_id: str, workspace_id: str) -> list[dict[str, object]]:
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

    def hard_delete_by_session(self, session_id: str, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "DELETE FROM messages WHERE session_id = ? AND workspace_id = ?",
            (session_id, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount

    def count_by_time_range(self, since: str) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE created_at >= ?",
            (since,),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0


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
        cur = self._db.connection.execute("SELECT rowid FROM memories WHERE id = ?", (mid,))
        row = cur.fetchone()
        if row:
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (row["rowid"], text, ""),
            )
            self._db.connection.commit()
        result = self.get_by_id(mid, workspace_id)
        assert result is not None
        return result

    def get_by_id(self, mid: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (mid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_workspace(self, workspace_id: str, limit: int = 50) -> list[dict[str, object]]:
        sql = (
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL ORDER BY created_at DESC LIMIT ?"
        )
        cur = self._db.connection.execute(sql, (workspace_id, limit))
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
            "UPDATE memories SET deleted_at = datetime('now') WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        cur = self._db.connection.execute("SELECT rowid FROM memories WHERE id = ?", (mid,))
        row = cur.fetchone()
        if row:
            self._db.connection.execute(
                "DELETE FROM memories_fts WHERE rowid = ?",
                (row["rowid"],),
            )
        try:
            self._db.connection.execute(
                "DELETE FROM memory_embeddings_v2 WHERE memory_id = ?", (mid,)
            )
        except Exception:
            pass
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
            "UPDATE memories SET text = ?, updated_at = datetime('now') WHERE id = ?",
            (merged_text, target_mid),
        )
        cur_ft = self._db.connection.execute(
            "SELECT rowid FROM memories WHERE id = ?", (target_mid,)
        )
        row_ft = cur_ft.fetchone()
        if row_ft:
            rowid = row_ft["rowid"]
            self._db.connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
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
            (
                version_id,
                workspace_id,
                str(old["type"]),
                old_text,
                str(old["summary"] or ""),
                float(old["confidence"] or 0.5),
                str(old["sensitivity"] or "normal"),
                mid,
            ),
        )
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (new_text, mid, workspace_id),
        )
        cur_ft = self._db.connection.execute("SELECT rowid FROM memories WHERE id = ?", (mid,))
        row = cur_ft.fetchone()
        if row:
            rowid = row["rowid"]
            self._db.connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (rowid, new_text, str(old["summary"] or "")),
            )
        self._db.connection.commit()
        return True

    def correct_text(
        self,
        mid: str,
        workspace_id: str,
        new_text: str,
        actor_id: str = "cli",
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
            (
                version_id,
                workspace_id,
                str(old["type"]),
                old_text,
                str(old["summary"] or ""),
                float(old["confidence"] or 0.5),
                str(old["sensitivity"] or "normal"),
                mid,
            ),
        )
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (new_text, mid, workspace_id),
        )
        cur_ft = self._db.connection.execute("SELECT rowid FROM memories WHERE id = ?", (mid,))
        row = cur_ft.fetchone()
        if row:
            rowid = row["rowid"]
            self._db.connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
            self._db.connection.execute(
                "INSERT INTO memories_fts(rowid, text, summary) VALUES (?, ?, ?)",
                (rowid, new_text, str(old["summary"] or "")),
            )
        self._db.connection.commit()
        return True

    def list_active_or_archived(
        self,
        workspace_id: str,
        *,
        memory_type: str = "",
        q: str = "",
        archived_filter: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List legacy memories with optional type, text, and archive filters."""
        sql = (
            "SELECT id, text, type, confidence, created_at, updated_at, archived_at"
            " FROM memories WHERE workspace_id=? AND deleted_at IS NULL"
        )
        params: list[object] = [workspace_id]
        if memory_type:
            sql += " AND type=?"
            params.append(memory_type)
        if archived_filter == "no":
            sql += " AND archived_at IS NULL"
        elif archived_filter == "yes":
            sql += " AND archived_at IS NOT NULL"
        if q:
            sql += " AND (text LIKE ? OR summary LIKE ?)"
            like = f"%{q}%"
            params.append(like)
            params.append(like)
        sql += " ORDER BY created_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def count_active(self, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM memories"
            " WHERE workspace_id=? AND deleted_at IS NULL AND archived_at IS NULL",
            (workspace_id,),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def count_archived(self, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM memories"
            " WHERE workspace_id=? AND archived_at IS NOT NULL AND deleted_at IS NULL",
            (workspace_id,),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

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
            sql,
            (fid, workspace_id, path, mime_type, sha256),
        )
        self._db.connection.commit()
        result = self.get_by_id(fid, workspace_id)
        assert result is not None
        return result

    def get_by_id(self, fid: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM file_artifacts WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (fid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM file_artifacts WHERE workspace_id = ? AND deleted_at IS NULL",
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
            "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
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
                    version_id,
                    workspace_id,
                    old["type"],
                    old_text,
                    old["summary"],
                    old["confidence"],
                    old["sensitivity"],
                    mid,
                ),
            )
        self._db.connection.execute(
            "UPDATE memories SET text = ?, updated_at = datetime('now')"
            " WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (text, mid, workspace_id),
        )
        self._db.connection.commit()
        cur = self._db.connection.execute("SELECT * FROM memories WHERE id = ?", (mid,))
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
        self._db.connection.execute("DELETE FROM memories_fts WHERE rowid = ?", (rowid,))
        try:
            self._db.connection.execute(
                "DELETE FROM memory_embeddings_v2 WHERE memory_id = ?", (mid,)
            )
        except Exception:
            pass
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
        tool_call_json: str = "",
    ) -> dict[str, object]:
        aid = str(uuid.uuid4())
        try:
            self._db.connection.execute(
                "INSERT INTO approval_records"
                " (id, workspace_id, session_id, actor_id, capability_name,"
                " operation, resource, reason, status, tool_call_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    aid,
                    workspace_id,
                    session_id,
                    actor_id,
                    capability_name,
                    operation,
                    resource,
                    reason,
                    tool_call_json,
                ),
            )
        except Exception:
            self._db.connection.execute(
                "INSERT INTO approval_records"
                " (id, workspace_id, session_id, actor_id, capability_name,"
                " operation, resource, reason, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (
                    aid,
                    workspace_id,
                    session_id,
                    actor_id,
                    capability_name,
                    operation,
                    resource,
                    reason,
                ),
            )
        self._db.connection.commit()
        cur = self._db.connection.execute("SELECT * FROM approval_records WHERE id = ?", (aid,))
        return dict(cur.fetchone())

    def get_by_id(self, aid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute("SELECT * FROM approval_records WHERE id = ?", (aid,))
        return _row_to_dict(cur.fetchone())

    def get_pending_tool_call(self, aid: str) -> str | None:
        try:
            cur = self._db.connection.execute(
                "SELECT tool_call_json FROM approval_records WHERE id = ? AND status = 'pending'",
                (aid,),
            )
            row = cur.fetchone()
            if row:
                val = row["tool_call_json"]
                return str(val) if val else None
        except Exception:
            pass
        return None

    def resolve(self, aid: str, decision: str, decided_by: str = "") -> dict[str, object] | None:
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
        cur = self._db.connection.execute("SELECT * FROM approval_records WHERE id = ?", (aid,))
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

    def list_by_workspace(self, workspace_id: str, limit: int = 50) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM approval_records"
            " WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_filters(
        self,
        workspace_id: str = "",
        *,
        status: str = "",
        risk: str = "",
        q: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List approval_records with optional status, risk, and search filters."""
        sql = "SELECT * FROM approval_records"
        params: list[object] = []
        clauses: list[str] = []
        if workspace_id and workspace_id != "*":
            clauses.append("workspace_id=?")
            params.append(workspace_id)
        if status and status != "all":
            clauses.append("status=?")
            params.append(status)
        if q:
            clauses.append("(capability_name LIKE ? OR operation LIKE ? OR resource LIKE ?)")
            like = f"%{q}%"
            params.append(like)
            params.append(like)
            params.append(like)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())


class AttachmentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        att_id: str,
        workspace_id: str,
        content_hash: str,
        media_type: str,
        original_filename: str,
        storage_path: str,
        size_bytes: int,
        width: int | None = None,
        height: int | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO attachments"
            " (id, workspace_id, session_id, content_hash, media_type,"
            " original_filename, storage_path, size_bytes, width, height)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                att_id,
                workspace_id,
                session_id,
                content_hash,
                media_type,
                original_filename,
                storage_path,
                size_bytes,
                width,
                height,
            ),
        )
        self._db.connection.commit()
        result = self.get_by_id(att_id, workspace_id)
        assert result is not None
        return result

    def get_by_id(self, att_id: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM attachments WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
            (att_id, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def get_by_hash(self, content_hash: str, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM attachments WHERE content_hash = ?"
            " AND workspace_id = ? AND deleted_at IS NULL",
            (content_hash, workspace_id),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM attachments WHERE workspace_id = ? AND deleted_at IS NULL"
            " ORDER BY created_at DESC",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_session(self, session_id: str, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM attachments WHERE session_id = ?"
            " AND workspace_id = ? AND deleted_at IS NULL"
            " ORDER BY created_at DESC",
            (session_id, workspace_id),
        )
        return _rows_to_dicts(cur.fetchall())

    def soft_delete(self, att_id: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE attachments SET deleted_at = datetime('now') WHERE id = ? AND workspace_id = ?",
            (att_id, workspace_id),
        )
        self._db.connection.commit()

    def hard_delete(self, att_id: str, workspace_id: str) -> bool:
        self._db.connection.execute(
            "DELETE FROM vision_observations WHERE attachment_id = ?", (att_id,)
        )
        self._db.connection.execute(
            "DELETE FROM message_attachments WHERE attachment_id = ?", (att_id,)
        )
        cur = self._db.connection.execute(
            "DELETE FROM attachments WHERE id = ? AND workspace_id = ?",
            (att_id, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0


class VisionObservationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        obs_id: str,
        workspace_id: str,
        attachment_id: str,
        image_content_hash: str,
        prompt: str,
        normalized_prompt: str,
        result_text: str,
        provider: str,
        model: str,
        preprocessing_version: str,
        cache_key: str,
        session_id: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        trace_id: str = "",
    ) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT OR IGNORE INTO vision_observations"
            " (id, workspace_id, session_id, attachment_id, image_content_hash,"
            " prompt, normalized_prompt, result_text, provider, model,"
            " preprocessing_version, cache_key, input_tokens, output_tokens,"
            " latency_ms, trace_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obs_id,
                workspace_id,
                session_id,
                attachment_id,
                image_content_hash,
                prompt,
                normalized_prompt,
                result_text,
                provider,
                model,
                preprocessing_version,
                cache_key,
                input_tokens,
                output_tokens,
                latency_ms,
                trace_id,
            ),
        )
        self._db.connection.commit()
        return self.get_by_cache_key(cache_key) or {}

    def get_by_cache_key(self, cache_key: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM vision_observations WHERE cache_key = ?",
            (cache_key,),
        )
        return _row_to_dict(cur.fetchone())

    def get_by_attachment(
        self, attachment_id: str, workspace_id: str, limit: int = 10
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM vision_observations"
            " WHERE attachment_id = ? AND workspace_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (attachment_id, workspace_id, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_workspace(self, workspace_id: str, limit: int = 50) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM vision_observations WHERE workspace_id = ?"
            " ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def hard_delete_by_attachment(self, attachment_id: str) -> None:
        self._db.connection.execute(
            "DELETE FROM vision_observations WHERE attachment_id = ?",
            (attachment_id,),
        )
        self._db.connection.commit()


class MemeAssetRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _row_to_asset(self, row: sqlite3.Row | None) -> dict[str, object] | None:
        if row is None:
            return None
        d = dict(row)
        for key in ("aliases_json", "emotions_json", "use_cases_json", "avoid_cases_json"):
            if isinstance(d.get(key), str):
                import json

                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = []
        return d

    def _rows_to_assets(self, rows: list[sqlite3.Row]) -> list[dict[str, object]]:
        assets: list[dict[str, object]] = []
        for row in rows:
            asset = self._row_to_asset(row)
            if asset is not None:
                assets.append(asset)
        return assets

    def create(
        self,
        meme_id: str,
        workspace_id: str,
        attachment_id: str,
        content_hash: str,
        name: str,
        description: str,
        source: str = "manual",
        aliases: list[str] | None = None,
        emotions: list[str] | None = None,
        use_cases: list[str] | None = None,
        avoid_cases: list[str] | None = None,
        text_on_image: str | None = None,
    ) -> dict[str, object]:
        import json
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "INSERT OR IGNORE INTO meme_assets"
            " (id, workspace_id, attachment_id, content_hash, name,"
            " aliases_json, description, emotions_json, use_cases_json,"
            " avoid_cases_json, text_on_image, source, enabled,"
            " use_count, last_used_at, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, NULL, ?, ?)",
            (
                meme_id,
                workspace_id,
                attachment_id,
                content_hash,
                name,
                json.dumps(aliases or [], ensure_ascii=False),
                description,
                json.dumps(emotions or [], ensure_ascii=False),
                json.dumps(use_cases or [], ensure_ascii=False),
                json.dumps(avoid_cases or [], ensure_ascii=False),
                text_on_image,
                source,
                now,
                now,
            ),
        )
        self._db.connection.commit()
        return self.get(meme_id, workspace_id) or {}

    def get(self, meme_id: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM meme_assets WHERE id = ? AND workspace_id = ?",
            (meme_id, workspace_id),
        )
        return self._row_to_asset(cur.fetchone())

    def get_by_attachment_id(
        self, attachment_id: str, workspace_id: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM meme_assets WHERE attachment_id = ? AND workspace_id = ?",
            (attachment_id, workspace_id),
        )
        return self._row_to_asset(cur.fetchone())

    def find_by_content_hash(self, content_hash: str, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM meme_assets WHERE content_hash = ? AND workspace_id = ?"
            " ORDER BY updated_at DESC",
            (content_hash, workspace_id),
        )
        return self._rows_to_assets(cur.fetchall())

    def list_enabled(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM meme_assets WHERE workspace_id = ? AND enabled = 1"
            " ORDER BY use_count DESC, updated_at DESC",
            (workspace_id,),
        )
        return self._rows_to_assets(cur.fetchall())

    def list_all(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM meme_assets WHERE workspace_id = ?"
            " ORDER BY use_count DESC, updated_at DESC",
            (workspace_id,),
        )
        return self._rows_to_assets(cur.fetchall())

    def search(self, workspace_id: str, query: str, limit: int = 10) -> list[dict[str, object]]:
        import unicodedata

        q = unicodedata.normalize("NFKC", query).lower().strip()
        if not q:
            return self.list_enabled(workspace_id)[:limit]
        keywords = [kw.strip() for kw in q.split() if kw.strip()]
        all_assets = self.list_enabled(workspace_id)
        scored: list[tuple[int, dict[str, object]]] = []
        for asset in all_assets:
            score = 0
            text_fields = [
                str(asset.get("name", "")),
                str(asset.get("description", "")),
                str(asset.get("text_on_image", "")),
            ]
            json_fields = [
                value if isinstance(value, list) else []
                for value in (
                    asset.get("aliases_json", []),
                    asset.get("emotions_json", []),
                    asset.get("use_cases_json", []),
                    asset.get("avoid_cases_json", []),
                )
            ]
            for kw in keywords:
                for field in text_fields:
                    if kw in unicodedata.normalize("NFKC", field).lower():
                        score += 2
                for lst in json_fields:
                    if isinstance(lst, list):
                        for item in lst:
                            if kw in unicodedata.normalize("NFKC", str(item)).lower():
                                score += 3
            if score > 0:
                scored.append((score, asset))
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:limit]]

    def update(
        self,
        meme_id: str,
        workspace_id: str,
        **kwargs: object,
    ) -> dict[str, object] | None:
        allowed = {
            "name",
            "aliases_json",
            "description",
            "emotions_json",
            "use_cases_json",
            "avoid_cases_json",
            "text_on_image",
            "source",
            "enabled",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get(meme_id, workspace_id)
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        updates["updated_at"] = now
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values())
        self._db.connection.execute(
            f"UPDATE meme_assets SET {cols} WHERE id = ? AND workspace_id = ?",  # noqa: S608
            [*vals, meme_id, workspace_id],
        )
        self._db.connection.commit()
        return self.get(meme_id, workspace_id)

    def record_use(self, meme_id: str, workspace_id: str) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        self._db.connection.execute(
            "UPDATE meme_assets SET use_count = use_count + 1, last_used_at = ?"
            " WHERE id = ? AND workspace_id = ?",
            (now, meme_id, workspace_id),
        )
        self._db.connection.commit()

    def delete(self, meme_id: str, workspace_id: str) -> bool:
        cur = self._db.connection.execute(
            "DELETE FROM meme_assets WHERE id = ? AND workspace_id = ?",
            (meme_id, workspace_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def count_by_workspace(self, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM meme_assets WHERE workspace_id = ?",
            (workspace_id,),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0


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
        return {
            "workspace_id": workspace_id,
            "quiet_hours_start": "",
            "quiet_hours_end": "",
            "timezone": "UTC",
            "max_daily_notifications": 3,
        }

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
                f"UPDATE workspace_settings SET ({cols}) = ({placeholders}) WHERE workspace_id = ?",
                [*values, workspace_id],
            )
        self._db.connection.commit()
        return self.get(workspace_id)


class MemoryItemRepository:
    """``memory_items`` table — structured memories (Memory v2)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        mid: str,
        workspace_id: str,
        memory_type: str,
        summary: str,
        content_hash: str,
        source_ref: str = "",
        emotional_weight: int = 0,
        extra_json: str = "{}",
    ) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO memory_items"
            " (id, workspace_id, memory_type, summary, content_hash,"
            "  source_ref, emotional_weight, extra_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, workspace_id, memory_type, summary, content_hash,
             source_ref, emotional_weight, extra_json),
        )
        self._db.connection.commit()
        return self.get_by_id(mid, workspace_id)

    def get_by_id(self, mid: str, workspace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_items WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        return _row_to_dict(cur.fetchone())

    def get_by_hash(
        self, content_hash: str, workspace_id: str, memory_type: str
    ) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_items"
            " WHERE workspace_id = ? AND content_hash = ? AND memory_type = ?",
            (workspace_id, content_hash, memory_type),
        )
        return _row_to_dict(cur.fetchone())

    def list_active_by_type(
        self, workspace_id: str, memory_type: str, limit: int = 20
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_items"
            " WHERE workspace_id = ? AND status = 'active' AND memory_type = ?"
            " ORDER BY updated_at DESC LIMIT ?",
            (workspace_id, memory_type, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_active(
        self,
        workspace_id: str,
        *,
        exclude_type: str = "",
        limit: int = 20,
    ) -> list[dict[str, object]]:
        if exclude_type:
            cur = self._db.connection.execute(
                "SELECT * FROM memory_items"
                " WHERE workspace_id = ? AND status='active' AND memory_type != ?"
                " ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, exclude_type, limit),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM memory_items"
                " WHERE workspace_id = ? AND status='active'"
                " ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return _rows_to_dicts(cur.fetchall())

    def list_by_type_desc(
        self,
        workspace_id: str,
        memory_type: str,
        sort_col: str = "updated_at",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT summary, memory_type, updated_at FROM memory_items"
            " WHERE workspace_id=? AND status='active' AND memory_type=?"
            " ORDER BY ? DESC LIMIT ?",
            (workspace_id, memory_type, sort_col, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def reinforce(self, mid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE memory_items SET reinforcement = reinforcement + 1,"
            " updated_at = datetime('now') WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        self._db.connection.commit()

    def supersede(self, mid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE memory_items SET status = 'superseded',"
            " updated_at = datetime('now') WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        self._db.connection.commit()

    def archive(self, mid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE memory_items SET status = 'archived',"
            " updated_at = datetime('now') WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        self._db.connection.commit()

    def soft_delete(self, mid: str, workspace_id: str) -> None:
        self._db.connection.execute(
            "UPDATE memory_items SET status = 'deleted',"
            " updated_at = datetime('now') WHERE id = ? AND workspace_id = ?",
            (mid, workspace_id),
        )
        self._db.connection.commit()

    def list_recent_by_types(
        self,
        workspace_id: str,
        types: tuple[str, ...],
        limit: int = 10,
    ) -> list[dict[str, object]]:
        placeholders = ", ".join("?" for _ in types)
        cur = self._db.connection.execute(
            "SELECT summary, memory_type, updated_at FROM memory_items"
            " WHERE workspace_id=? AND status='active'"
            f" AND memory_type IN ({placeholders})"
            " ORDER BY"
            "   CASE memory_type"
            "     WHEN 'profile' THEN 1"
            "     WHEN 'preference' THEN 2"
            "     WHEN 'procedure' THEN 3"
            "     ELSE 4"
            "   END,"
            "   updated_at DESC LIMIT ?",
            (workspace_id, *types, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def count_active(self, workspace_id: str, exclude_type: str = "") -> int:
        if exclude_type:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM memory_items"
                " WHERE workspace_id=? AND status='active' AND memory_type != ?",
                (workspace_id, exclude_type),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM memory_items"
                " WHERE workspace_id=? AND status='active'",
                (workspace_id,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def list_active_with_filters(
        self,
        workspace_id: str,
        *,
        memory_type: str = "",
        q: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List active memory_items with optional type and text filters."""
        sql = (
            "SELECT id, summary AS text, memory_type AS type, reinforcement,"
            " emotional_weight, created_at, updated_at FROM memory_items"
            " WHERE workspace_id=? AND status='active' AND memory_type != '_recent_context'"
        )
        params: list[object] = [workspace_id]
        if memory_type:
            sql += " AND memory_type=?"
            params.append(memory_type)
        if q:
            sql += " AND summary LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY updated_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def count_by_status_grouped(self, workspace_id: str) -> dict[str, int]:
        """Return counts of active/archived/superseded memory items."""
        cur = self._db.connection.execute(
            "SELECT status, COUNT(*) AS cnt FROM memory_items"
            " WHERE workspace_id=? AND memory_type != '_recent_context'"
            " GROUP BY status",
            (workspace_id,),
        )
        return {str(row["status"]): row["cnt"] for row in cur.fetchall()}


class TraceRepository:
    """``traces`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_by_workspace(
        self, workspace_id: str = "", limit: int = 20, offset: int = 0
    ) -> list[dict[str, object]]:
        if workspace_id and workspace_id != "*":
            cur = self._db.connection.execute(
                "SELECT id, workspace_id, session_id, root_event_id,"
                " status, started_at, ended_at"
                " FROM traces WHERE workspace_id=? ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (workspace_id, limit, offset),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT id, workspace_id, session_id, root_event_id,"
                " status, started_at, ended_at"
                " FROM traces ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return _rows_to_dicts(cur.fetchall())

    def get_spans_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at", (trace_id,)
        )
        return _rows_to_dicts(cur.fetchall())

    def get_source_lineage_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM source_lineage WHERE trace_id = ? ORDER BY rowid", (trace_id,)
        )
        return _rows_to_dicts(cur.fetchall())

    def get_context_items_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM context_items WHERE trace_id = ? ORDER BY rank", (trace_id,)
        )
        return _rows_to_dicts(cur.fetchall())

    def list_spans_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT sp.* FROM spans sp"
            " JOIN traces t ON sp.trace_id = t.id"
            " WHERE t.workspace_id = ?",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def count_by_time_range(self, since: str, workspace_id: str = "") -> int:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM traces"
                " WHERE started_at >= ? AND workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM traces WHERE started_at >= ?",
                (since,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def count_failed_by_time_range(self, since: str, workspace_id: str = "") -> int:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM traces"
                " WHERE started_at >= ? AND status='error' AND workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM traces"
                " WHERE started_at >= ? AND status='error'",
                (since,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def get_by_id(self, trace_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (trace_id,)
        )
        return _row_to_dict(cur.fetchone())

    def get_detail_with_spans(self, trace_id: str) -> dict[str, object] | None:
        """Return a trace with its spans, model_calls, tool_calls, and audits."""
        trace = self.get_by_id(trace_id)
        if trace is None:
            return None
        spans = self._db.connection.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at", (trace_id,)
        )
        trace["spans"] = _rows_to_dicts(spans.fetchall())
        model_calls = self._db.connection.execute(
            "SELECT provider, model, input_token_count, output_token_count,"
            " latency_ms, stop_reason, error FROM model_calls"
            " WHERE trace_id = ? ORDER BY id", (trace_id,)
        )
        trace["model_calls"] = _rows_to_dicts(model_calls.fetchall())
        tool_calls = self._db.connection.execute(
            "SELECT capability_name, decision, status, latency_ms, error"
            " FROM tool_calls WHERE trace_id = ? ORDER BY id", (trace_id,)
        )
        trace["tool_calls"] = _rows_to_dicts(tool_calls.fetchall())
        audits = self._db.connection.execute(
            "SELECT action, decision, reason, created_at FROM audit_logs"
            " WHERE trace_id = ? ORDER BY created_at", (trace_id,)
        )
        trace["audits"] = _rows_to_dicts(audits.fetchall())
        return trace

    def list_by_filters(
        self,
        workspace_id: str,
        *,
        status: str = "",
        q: str = "",
        time_range: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        from datetime import UTC, datetime, timedelta
        sql = "SELECT * FROM traces WHERE workspace_id=?"
        params: list[object] = [workspace_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        if time_range and time_range != "all":
            days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
            days = days_map.get(time_range, 0)
            if days:
                cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                sql += " AND started_at >= ?"
                params.append(cutoff)
        if q:
            sql += " AND (id LIKE ? OR session_id LIKE ?)"
            like = f"%{q}%"
            params.append(like)
            params.append(like)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def count_by_filters(
        self,
        workspace_id: str,
        *,
        status: str = "",
        time_range: str = "",
    ) -> int:
        from datetime import UTC, datetime, timedelta
        sql = "SELECT COUNT(*) AS cnt FROM traces WHERE workspace_id=?"
        params: list[object] = [workspace_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        if time_range and time_range != "all":
            days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
            days = days_map.get(time_range, 0)
            if days:
                cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                sql += " AND started_at >= ?"
                params.append(cutoff)
        cur = self._db.connection.execute(sql, params)
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def hard_delete_by_workspace(self, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "DELETE FROM traces WHERE workspace_id = ?", (workspace_id,)
        )
        self._db.connection.commit()
        return cur.rowcount

    def cleanup_old_traces_before(self, workspace_id: str, cutoff: str) -> int:
        """Hard-delete completed traces ended before the cutoff datetime."""
        cur = self._db.connection.execute(
            "DELETE FROM traces WHERE workspace_id=? AND ended_at IS NOT NULL"
            " AND ended_at < ?",
            (workspace_id, cutoff),
        )
        self._db.connection.commit()
        return cur.rowcount


class ModelCallRepository:
    """``model_calls`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def count_by_time_range(self, since: str, workspace_id: str = "") -> int:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM model_calls mc"
                " JOIN traces t ON mc.trace_id = t.id"
                " WHERE t.started_at >= ? AND t.workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM model_calls mc"
                " JOIN traces t ON mc.trace_id = t.id"
                " WHERE t.started_at >= ?",
                (since,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def avg_latency(self, since: str, workspace_id: str = "") -> float:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT AVG(mc.latency_ms) AS avg_lat FROM model_calls mc"
                " JOIN traces t ON mc.trace_id = t.id"
                " WHERE t.started_at >= ? AND mc.latency_ms > 0"
                " AND t.workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT AVG(mc.latency_ms) AS avg_lat FROM model_calls mc"
                " JOIN traces t ON mc.trace_id = t.id"
                " WHERE t.started_at >= ? AND mc.latency_ms > 0",
                (since,),
            )
        row = cur.fetchone()
        return round(row["avg_lat"], 1) if row and row["avg_lat"] else 0.0

    def list_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT provider, model, input_token_count, output_token_count,"
            " latency_ms, stop_reason, error FROM model_calls"
            " WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT mc.* FROM model_calls mc"
            " JOIN traces t ON mc.trace_id = t.id"
            " WHERE t.workspace_id = ?",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())


class ToolCallRepository:
    """``tool_calls`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def count_by_time_range(self, since: str, workspace_id: str = "") -> int:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM tool_calls tc"
                " JOIN traces t ON tc.trace_id = t.id"
                " WHERE t.started_at >= ? AND t.workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM tool_calls tc"
                " JOIN traces t ON tc.trace_id = t.id"
                " WHERE t.started_at >= ?",
                (since,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def list_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT capability_name, decision, status, latency_ms, error"
            " FROM tool_calls WHERE trace_id = ? ORDER BY id",
            (trace_id,),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_by_workspace(self, workspace_id: str) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT tc.* FROM tool_calls tc"
            " JOIN traces t ON tc.trace_id = t.id"
            " WHERE t.workspace_id = ?",
            (workspace_id,),
        )
        return _rows_to_dicts(cur.fetchall())


class OutboxRepository:
    """``outbox_messages`` table — autonomous notification outbox."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        *,
        mid: str,
        event_id: str,
        decision_id: str,
        workspace_id: str,
        user_id: str,
        title: str,
        body: str = "",
        priority: str = "normal",
        source: str = "system",
        trace_id: str = "",
        status: str = "pending",
    ) -> dict[str, object]:
        self._db.connection.execute(
            "INSERT INTO outbox_messages"
            " (id, event_id, decision_id, workspace_id, user_id,"
            "  title, body, status, priority, source, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (mid, event_id, decision_id, workspace_id, user_id,
             title, body, status, priority, source, trace_id),
        )
        self._db.connection.commit()
        return {
            "id": mid,
            "event_id": event_id,
            "decision_id": decision_id,
            "workspace_id": workspace_id,
            "status": status,
        }

    def get_by_id(self, mid: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM outbox_messages WHERE id = ?", (mid,)
        )
        return _row_to_dict(cur.fetchone())

    def list_by_status(
        self,
        statuses: tuple[str, ...],
        workspace_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, object]]:
        placeholders = ", ".join("?" for _ in statuses)
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT * FROM outbox_messages"
                f" WHERE status IN ({placeholders}) AND workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (*statuses, workspace_id, limit),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM outbox_messages"
                f" WHERE status IN ({placeholders})"
                " ORDER BY created_at DESC LIMIT ?",
                (*statuses, limit),
            )
        return _rows_to_dicts(cur.fetchall())

    def list_failed(
        self, workspace_id: str = "", limit: int = 5
    ) -> list[dict[str, object]]:
        return self.list_by_status(
            ("failed", "dead_letter"), workspace_id=workspace_id, limit=limit
        )

    def list_pending(self, workspace_id: str = "", limit: int = 50) -> list[dict[str, object]]:
        return self.list_by_status(
            ("pending",), workspace_id=workspace_id, limit=limit
        )

    def count_by_status(
        self, statuses: tuple[str, ...], workspace_id: str = ""
    ) -> int:
        placeholders = ", ".join("?" for _ in statuses)
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM outbox_messages"
                f" WHERE status IN ({placeholders}) AND workspace_id = ?",
                (*statuses, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM outbox_messages"
                f" WHERE status IN ({placeholders})",
                (*statuses,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def update_status(
        self, mid: str, status: str, extra: dict[str, str] | None = None
    ) -> None:
        extras = extra or {}
        set_clause = "status = ?"
        vals: list[str | None] = [status]
        if "sent_at" in extras:
            set_clause += ", sent_at = ?"
            vals.append(extras["sent_at"])
        if "error" in extras:
            set_clause += ", last_error = ?"
            vals.append(extras["error"])
        if "title" in extras:
            set_clause += ", title = ?"
            vals.append(extras["title"])
        self._db.connection.execute(
            f"UPDATE outbox_messages SET {set_clause} WHERE id = ?",
            [*vals, mid],
        )
        self._db.connection.commit()

    def mark_failed(self, mid: str, error: str) -> None:
        self.update_status(mid, "failed", {"error": error})

    def mark_dead_letter(self, mid: str, error: str) -> None:
        self.update_status(mid, "dead_letter", {"error": error})

    def list_by_filters(
        self,
        workspace_id: str,
        *,
        status: str = "",
        q: str = "",
        time_range: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """List outbox_messages with optional status, text, and time-range filters."""
        from datetime import UTC, datetime, timedelta
        sql = "SELECT *, 'outbox' AS source FROM outbox_messages"
        params: list[object] = []
        clauses: list[str] = []
        if workspace_id:
            clauses.append("workspace_id = ?")
            params.append(workspace_id)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if time_range and time_range != "all":
            days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
            days = days_map.get(time_range, 0)
            if days:
                cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
                clauses.append("created_at >= ?")
                params.append(cutoff)
        if q:
            clauses.append("(title LIKE ? OR body LIKE ?)")
            like = f"%{q}%"
            params.append(like)
            params.append(like)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def count_by_status_grouped(self, workspace_id: str) -> dict[str, int]:
        """Return counts per status for outbox_messages."""
        cur = self._db.connection.execute(
            "SELECT status, COUNT(*) AS cnt FROM outbox_messages"
            " WHERE workspace_id=? GROUP BY status",
            (workspace_id,),
        )
        return {str(row["status"]): row["cnt"] for row in cur.fetchall()}


class DriftRunRepository:
    """``drift_runs`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_by_workspace(
        self, workspace_id: str, limit: int = 20
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT id, skill_name, status, created_at FROM drift_runs"
            " WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_failed(
        self, since: str, workspace_id: str = "", limit: int = 5
    ) -> list[dict[str, object]]:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT id, skill_name, error_message FROM drift_runs"
                " WHERE status='failed' AND created_at >= ? AND workspace_id = ?"
                " ORDER BY created_at DESC LIMIT ?",
                (since, workspace_id, limit),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT id, skill_name, error_message FROM drift_runs"
                " WHERE status='failed' AND created_at >= ?"
                " ORDER BY created_at DESC LIMIT ?",
                (since, limit),
            )
        return _rows_to_dicts(cur.fetchall())

    def count_failed(self, since: str, workspace_id: str = "") -> int:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM drift_runs"
                " WHERE status='failed' AND created_at >= ? AND workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM drift_runs"
                " WHERE status='failed' AND created_at >= ?",
                (since,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0


class DriftStateRepository:
    """``drift_state`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT enabled FROM drift_state WHERE id='main'"
        )
        return _row_to_dict(cur.fetchone())

    def set_enabled(self, enabled: bool) -> None:
        self._db.connection.execute(
            "INSERT INTO drift_state (id, enabled) VALUES ('main', ?)"
            " ON CONFLICT(id) DO UPDATE SET enabled = ?",
            (1 if enabled else 0, 1 if enabled else 0),
        )
        self._db.connection.commit()


class DecisionRepository:
    """``notification_decisions`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, decision: dict[str, object]) -> None:
        self._db.connection.execute(
            "INSERT INTO notification_decisions"
            " (id, event_id, workspace_id, user_id, action, reason_code, reason,"
            "  cost_score, priority_score, dedup_hit, quiet_hours_hit, quota_hit,"
            "  requires_approval, trace_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision["id"],
                decision["event_id"],
                decision.get("workspace_id", "*"),
                decision.get("user_id", ""),
                decision["action"],
                decision.get("reason_code", ""),
                decision.get("reason", ""),
                decision.get("cost_score", 0.0),
                decision.get("priority_score", 0.0),
                1 if decision.get("dedup_hit") else 0,
                1 if decision.get("quiet_hours_hit") else 0,
                1 if decision.get("quota_hit") else 0,
                1 if decision.get("requires_approval") else 0,
                decision.get("trace_id", ""),
                decision.get("created_at", ""),
            ),
        )


    def list_by_workspace(
        self,
        workspace_id: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM notification_decisions"
                " ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM notification_decisions"
                " WHERE workspace_id=? OR workspace_id='*'"
                " ORDER BY created_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return _rows_to_dicts(cur.fetchall())

    def count_by_time_range(self, since: str) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM notification_decisions WHERE created_at >= ?",
            (since,),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0


class DaemonStateRepository:
    """``daemon_state`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT status, crash_marker FROM daemon_state WHERE id = 'main'"
        )
        return _row_to_dict(cur.fetchone())

    def update(self, **kwargs: str | None) -> None:
        now = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        vals = list(kwargs.values())
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        self._db.connection.execute(
            "INSERT INTO daemon_state (id, status, updated_at)"
            " VALUES ('main', 'running', ?)"
            " ON CONFLICT(id) DO UPDATE SET status = COALESCE(?, status), updated_at = ?",
            (now, kwargs.get("status"), now),
        )
        if cols:
            self._db.connection.execute(
                f"INSERT INTO daemon_state (id, {cols}, updated_at)"
                f" VALUES ('main', {placeholders}, ?)"
                f" ON CONFLICT(id) DO UPDATE SET {set_clause}, updated_at = ?",
                [*vals, now, *vals, now],
            )
        self._db.connection.commit()


class AuditRepository:
    """``audit_logs`` table — read-only query access.

    Writes go through ``AuditLogger`` in ``cogito_agent.governance.audit``.
    This repository fills the read-side gap so views and CLIs never write raw SQL.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_by_filters(
        self,
        workspace_id: str = "",
        *,
        action: str = "",
        actor: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        sql = "SELECT al.* FROM audit_logs al"
        params: list[object] = []
        clauses: list[str] = []
        if workspace_id:
            clauses.append("al.workspace_id = ?")
            params.append(workspace_id)
        if action:
            clauses.append("al.action = ?")
            params.append(action)
        if actor:
            clauses.append("al.actor_id = ?")
            params.append(actor)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY al.created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def list_by_time_range(
        self,
        since: str,
        workspace_id: str = "",
        *,
        action: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        sql = "SELECT al.* FROM audit_logs al"
        params: list[object] = []
        clauses: list[str] = ["al.created_at >= ?"]
        params.append(since)
        if workspace_id:
            clauses.append("al.workspace_id = ?")
            params.append(workspace_id)
        if action:
            clauses.append("al.action = ?")
            params.append(action)
        sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY al.created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def count_by_time_range(self, since: str, workspace_id: str = "") -> int:
        if workspace_id:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM audit_logs"
                " WHERE created_at >= ? AND workspace_id = ?",
                (since, workspace_id),
            )
        else:
            cur = self._db.connection.execute(
                "SELECT COUNT(*) AS cnt FROM audit_logs WHERE created_at >= ?",
                (since,),
            )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def get_by_id(self, audit_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM audit_logs WHERE id = ?", (audit_id,)
        )
        return _row_to_dict(cur.fetchone())

    def list_by_advanced_filters(
        self,
        *,
        workspace_id: str = "",
        actor: str = "",
        operation: str = "",
        q: str = "",
        since: str = "",
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """List audit_logs with dynamic filters — used by console/audit_views."""
        sql = "SELECT al.* FROM audit_logs al"
        params: list[object] = []
        clauses: list[str] = []
        if workspace_id and workspace_id != "*":
            clauses.append("al.workspace_id=?")
            params.append(workspace_id)
        if actor:
            clauses.append("al.actor_id=?")
            params.append(actor)
        if operation:
            clauses.append("al.action LIKE ?")
            params.append(f"%{operation}%")
        if q:
            clauses.append(
                "(al.actor_id LIKE ? OR al.action LIKE ?"
                " OR al.resource LIKE ? OR al.trace_id LIKE ?"
                " OR al.reason LIKE ?)"
            )
            like = f"%{q}%"
            for _ in range(5):
                params.append(like)
        if since:
            clauses.append("al.created_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY al.created_at DESC LIMIT ?"
        params.append(limit)
        cur = self._db.connection.execute(sql, params)
        return _rows_to_dicts(cur.fetchall())

    def count_by_filters(
        self,
        workspace_id: str = "",
    ) -> int:
        wc = "WHERE workspace_id=?" if workspace_id and workspace_id != "*" else ""
        params = (workspace_id,) if workspace_id and workspace_id != "*" else ()
        row = self._db.connection.execute(
            f"SELECT COUNT(*) AS cnt FROM audit_logs {wc}", params
        ).fetchone()
        return row["cnt"] if row else 0
