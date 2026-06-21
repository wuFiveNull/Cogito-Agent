from __future__ import annotations

import logging
import re

from cogito_agent.storage import Database

logger = logging.getLogger(__name__)


def _sanitize_fts_query(query: str) -> str:
    """Escape special FTS5 characters to prevent syntax errors."""
    sanitized = re.sub(r'[\'"]', " ", query)
    sanitized = re.sub(r"[\(\)\*\:\-\+]", " ", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if not sanitized:
        sanitized = "NULL"
    return sanitized


def _normalize_bm25(score: float) -> float:
    """Normalize BM25 score to [0, 1].

    SQLite FTS5 bm25() returns lower (more negative) scores for better matches.
    Invert so that a strongly negative BM25 → high normalized score.
    """
    relevance = max(0.0, -score)
    return relevance / (1.0 + relevance)


class SparseMemoryRetriever:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 40,
        include_archived: bool = False,
    ) -> list[dict[str, object]]:
        results = self._fts_search(workspace_id, query, limit, include_archived)
        if not results:
            results = self._like_search(workspace_id, query, limit, include_archived)
        for r in results:
            raw = r.get("_bm25_score")
            if isinstance(raw, (int, float)):
                r["sparse_score"] = _normalize_bm25(float(raw))
            else:
                r["sparse_score"] = 0.0
            r.pop("_bm25_score", None)
        return results

    def _fts_search(
        self,
        workspace_id: str,
        query: str,
        limit: int,
        include_archived: bool,
    ) -> list[dict[str, object]]:
        safe_query = _sanitize_fts_query(query)
        if safe_query == "NULL":
            return []
        archived_clause = "" if include_archived else " AND m.archived_at IS NULL"
        try:
            cur = self._db.connection.execute(
                "SELECT m.*, bm25(memories_fts, 0.0, 1.0) AS _bm25_score"
                " FROM memories m"
                " JOIN memories_fts fts ON m.rowid = fts.rowid"
                " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
                + archived_clause
                + " AND memories_fts MATCH ?"
                " ORDER BY _bm25_score ASC LIMIT ?",
                (workspace_id, safe_query, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("FTS query failed: %s, falling back to LIKE", e)
            return []

    def _like_search(
        self,
        workspace_id: str,
        query: str,
        limit: int,
        include_archived: bool,
    ) -> list[dict[str, object]]:
        archived_clause = "" if include_archived else " AND archived_at IS NULL"
        try:
            cur = self._db.connection.execute(
                "SELECT * FROM memories WHERE workspace_id = ?"
                " AND deleted_at IS NULL" + archived_clause + " AND (text LIKE ? OR summary LIKE ?)"
                " ORDER BY confidence DESC, created_at DESC LIMIT ?",
                (workspace_id, f"%{query}%", f"%{query}%", limit),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("LIKE search failed: %s", e)
            return []
