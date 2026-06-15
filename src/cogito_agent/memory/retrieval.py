from __future__ import annotations

from cogito_agent.storage import Database


class MemoryRetriever:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(self, workspace_id: str, query: str, limit: int = 10) -> list[dict[str, object]]:
        try:
            cur = self._db.connection.execute(
                "SELECT m.* FROM memories m"
                " JOIN memories_fts fts ON m.rowid = fts.rowid"
                " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
                " AND memories_fts MATCH ?"
                " ORDER BY rank LIMIT ?",
                (workspace_id, query, limit),
            )
            results = [dict(r) for r in cur.fetchall()]
            if results:
                return results
        except Exception:
            pass
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL"
            " AND (text LIKE ? OR summary LIKE ?)"
            " ORDER BY confidence DESC, created_at DESC LIMIT ?",
            (workspace_id, f"%{query}%", f"%{query}%", limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def search_hybrid(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        bm25_weight: float = 0.5,
        semantic_weight: float = 0.5,
    ) -> list[dict[str, object]]:
        try:
            from cogito_agent.memory.vector import HybridRetriever

            hybrid = HybridRetriever(self._db)
            return hybrid.search(workspace_id, query, limit, bm25_weight, semantic_weight)
        except Exception:
            return self.search(workspace_id, query, limit)

    def list_recent(self, workspace_id: str, limit: int = 20) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL"
            " ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
