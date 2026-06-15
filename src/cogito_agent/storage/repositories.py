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
        result = self.get_by_id(mid, workspace_id)
        assert result is not None
        return result

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
        self._db.connection.commit()


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


class MemoryEditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def update_text(self, mid: str, workspace_id: str, text: str) -> dict[str, object] | None:
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
