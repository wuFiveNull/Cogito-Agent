from __future__ import annotations

import re

from cogito_agent.storage import Database

_TYPE_PRIORITY: dict[str, int] = {
    "profile": 10,
    "preference": 8,
    "task": 7,
    "project": 6,
    "relationship": 5,
    "episodic": 4,
    "skill": 3,
    "general": 1,
}


def _score_memory(
    memory: dict[str, object], query: str | None = None,
) -> float:
    raw_type = memory.get("type", "general")
    type_str = str(raw_type) if raw_type is not None else "general"
    score = float(_TYPE_PRIORITY.get(type_str, 1))

    raw_confidence = memory.get("confidence")
    if isinstance(raw_confidence, (int, float)):
        confidence = float(raw_confidence)
    else:
        confidence = 0.5
    score *= confidence

    if query:
        text = str(memory.get("text", ""))
        if query.lower() in text.lower():
            score *= 1.5
        words = set(re.sub(r'[^\w\s]', '', query.lower()).split())
        text_words = set(re.sub(r'[^\w\s]', '', text.lower()).split())
        overlap = len(words & text_words)
        if overlap > 0:
            score *= (1.0 + 0.2 * min(overlap, 5))

    if memory.get("status") in ("consolidated", "indexed"):
        score *= 1.2

    return score


class MemoryRetriever:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(
        self, workspace_id: str, query: str, limit: int = 10,
    ) -> list[dict[str, object]]:
        fts_results: list[dict[str, object]] = []
        try:
            cur = self._db.connection.execute(
                "SELECT m.* FROM memories m"
                " JOIN memories_fts fts ON m.rowid = fts.rowid"
                " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
                " AND memories_fts MATCH ?"
                " ORDER BY rank LIMIT ?",
                (workspace_id, query, limit),
            )
            fts_results = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

        like_results: list[dict[str, object]] = []
        if not fts_results:
            cur = self._db.connection.execute(
                "SELECT * FROM memories WHERE workspace_id = ?"
                " AND deleted_at IS NULL"
                " AND (text LIKE ? OR summary LIKE ?)"
                " ORDER BY confidence DESC, created_at DESC LIMIT ?",
                (workspace_id, f"%{query}%", f"%{query}%", limit),
            )
            like_results = [dict(r) for r in cur.fetchall()]

        combined = fts_results or like_results
        scored = [
            (m, _score_memory(m, query)) for m in combined
        ]
        scored.sort(key=lambda x: -x[1])
        return [m for m, _ in scored[:limit]]

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
            return hybrid.search(
                workspace_id, query, limit, bm25_weight, semantic_weight
            )
        except Exception:
            return self.search(workspace_id, query, limit)

    def list_recent(
        self, workspace_id: str, limit: int = 20,
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL"
            " ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
