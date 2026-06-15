from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cogito_agent.storage import Database

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(data: bytes) -> list[float]:
    return list(struct.unpack(f"{len(data) // 4}f", data))


class EmbeddingService:
    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        except ImportError:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Run: pip install cogito-agent[vector]"
            )

    def encode(self, text: str) -> list[float]:
        self._load_model()
        assert self._model is not None
        result = self._model.encode(text, normalize_embeddings=True)
        return result.tolist()

    def compute_similarity(self, query_vec: list[float], doc_vec: list[float]) -> float:
        return _cosine_similarity(query_vec, doc_vec)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return _EMBEDDING_DIM


class HybridRetriever:
    def __init__(self, db: Database, embedding_service: EmbeddingService | None = None) -> None:
        self._db = db
        self._embedding_service = embedding_service or EmbeddingService()

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        bm25_weight: float = 0.5,
        semantic_weight: float = 0.5,
    ) -> list[dict[str, object]]:
        if not self._has_embeddings():
            return self._fts_only_search(workspace_id, query, limit)

        query_vec = self._embedding_service.encode(query)

        bm25_candidates = self._fts_search_raw(workspace_id, query, limit * 3)

        scored: list[tuple[dict[str, object], float]] = []
        for row in bm25_candidates:
            mem_id = str(row["id"])
            emb_bytes = self._get_embedding(mem_id)
            semantic_score = 0.0
            if emb_bytes:
                doc_vec = _unpack_embedding(emb_bytes)
                semantic_score = self._embedding_service.compute_similarity(query_vec, doc_vec)
            bm25_score = 0.0
            raw = row.get("_bm25_score")
            if isinstance(raw, (int, float)):
                bm25_score = float(raw)
            combined = bm25_weight * bm25_score + semantic_weight * semantic_score
            scored.append((row, combined))

        if not scored:
            return self._fts_only_search(workspace_id, query, limit)

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [r for r, _ in scored[:limit]]
        for r in results:
            r.pop("_bm25_score", None)
        return results

    def _has_embeddings(self) -> bool:
        try:
            cur = self._db.connection.execute(
                "SELECT 1 FROM memory_embeddings LIMIT 1"
            )
            return cur.fetchone() is not None
        except Exception:
            return False

    def _fts_search_raw(
        self, workspace_id: str, query: str, limit: int
    ) -> list[dict[str, object]]:
        try:
            cur = self._db.connection.execute(
                "SELECT m.*, bm25(memories_fts, 0.0, 1.0) AS _bm25_score"
                " FROM memories m"
                " JOIN memories_fts fts ON m.rowid = fts.rowid"
                " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
                " AND memories_fts MATCH ?"
                " ORDER BY _bm25_score ASC LIMIT ?",
                (workspace_id, query, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

    def _fts_only_search(
        self, workspace_id: str, query: str, limit: int
    ) -> list[dict[str, object]]:
        from .retrieval import MemoryRetriever
        return MemoryRetriever(self._db).search(workspace_id, query, limit)

    def _get_embedding(self, memory_id: str) -> bytes | None:
        cur = self._db.connection.execute(
            "SELECT embedding FROM memory_embeddings WHERE memory_id = ?",
            (memory_id,),
        )
        row = cur.fetchone()
        return row["embedding"] if row else None
