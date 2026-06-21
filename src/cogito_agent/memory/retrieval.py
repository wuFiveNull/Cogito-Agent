from __future__ import annotations

import logging
import re
from typing import Any

from cogito_agent.storage import Database

logger = logging.getLogger(__name__)

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
    memory: dict[str, object],
    query: str | None = None,
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
        words = set(re.sub(r"[^\w\s]", "", query.lower()).split())
        text_words = set(re.sub(r"[^\w\s]", "", text.lower()).split())
        overlap = len(words & text_words)
        if overlap > 0:
            score *= 1.0 + 0.2 * min(overlap, 5)

    if memory.get("status") in ("consolidated", "indexed"):
        score *= 1.2

    if memory.get("pinned_at") is not None:
        score *= 2.0

    return score


class MemoryRetriever:
    def __init__(
        self,
        db: Database,
        service: Any = None,
    ) -> None:
        self._db = db
        self._service = service

    def _ensure_service(self) -> None:
        if self._service is None:
            from cogito_agent.retrieval.service import create_retrieval_service

            self._service = create_retrieval_service(self._db)

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[dict[str, object]]:
        self._ensure_service()
        result: list[dict[str, object]] = self._service.search_compat(
            workspace_id,
            query,
            limit=limit,
            include_archived=include_archived,
        )
        return result

    def search_with_lineage(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[dict[str, object]]:
        results = self.search(workspace_id, query, limit, include_archived)
        for m in results:
            source_id = m.get("source_id")
            if source_id:
                cur = self._db.connection.execute(
                    "SELECT id, text, type FROM memories WHERE id = ?",
                    (source_id,),
                )
                source = cur.fetchone()
                m["source_lineage"] = dict(source) if source else None
            else:
                m["source_lineage"] = None
        return results

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
                workspace_id,
                query,
                limit,
                bm25_weight=bm25_weight,
                semantic_weight=semantic_weight,
            )
        except Exception:
            return self.search(workspace_id, query, limit)

    def list_recent(
        self,
        workspace_id: str,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM memories WHERE workspace_id = ?"
            " AND deleted_at IS NULL"
            " ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
