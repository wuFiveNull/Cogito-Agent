from __future__ import annotations

import datetime
import hashlib
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


class MockEmbeddingService:
    """Deterministic mock embedding that does NOT require sentence-transformers.

    Generates a fixed-dimension vector derived from a hash of the input text.
    Vectors are normalized to unit length for meaningful cosine similarity.
    """

    def __init__(self, dimension: int = _EMBEDDING_DIM) -> None:
        self._dimension = dimension
        self._model_name = "mock"

    def encode(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = []
        for i in range(self._dimension):
            idx = i % len(h)
            val = (h[idx] - 128) / 128.0
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def compute_similarity(self, query_vec: list[float], doc_vec: list[float]) -> float:
        return _cosine_similarity(query_vec, doc_vec)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension


class EmbeddingService:
    """Real embedding service using sentence-transformers, with MockEmbeddingService fallback."""

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None
        self._mock: MockEmbeddingService | None = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        except ImportError:
            self._mock = MockEmbeddingService()

    def encode(self, text: str) -> list[float]:
        self._load_model()
        if self._mock is not None:
            return self._mock.encode(text)
        assert self._model is not None
        result = self._model.encode(text, normalize_embeddings=True)
        return result.tolist()

    def compute_similarity(self, query_vec: list[float], doc_vec: list[float]) -> float:
        return _cosine_similarity(query_vec, doc_vec)

    @property
    def model_name(self) -> str:
        return self._mock.model_name if self._mock else self._model_name

    @property
    def dimension(self) -> int:
        return self._mock.dimension if self._mock else _EMBEDDING_DIM


class HybridRetriever:
    def __init__(self, db: Database, embedding_service: EmbeddingService | None = None) -> None:
        self._db = db
        self._embedding_service = embedding_service or EmbeddingService()

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        include_archived: bool = False,
        bm25_weight: float = 0.35,
        semantic_weight: float = 0.35,
    ) -> list[dict[str, object]]:
        if not self._has_embeddings():
            return self._fts_only_search(workspace_id, query, limit, include_archived)

        query_vec = self._embedding_service.encode(query)

        bm25_candidates = self._fts_search_raw(workspace_id, query, limit * 3, include_archived)

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
            # Normalize BM25 to [0, 1] via 1/(1+x)
            norm_bm25 = 1.0 / (1.0 + bm25_score)
            # Semantic is already in [0, 1] from cosine similarity
            # Recency bonus: 1/(1+days_since_update), capped at 1.0
            updated_raw = row.get("updated_at") or row.get("created_at") or ""
            days_since_update = 0.0
            try:
                if isinstance(updated_raw, str) and updated_raw:
                    dt = datetime.datetime.fromisoformat(updated_raw)
                    now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
                    days_since_update = max(0.0, (now - dt).total_seconds() / 86400.0)
            except (ValueError, TypeError):
                pass
            recency_bonus = 1.0 / (1.0 + days_since_update)
            # Confidence score
            raw_conf = row.get("confidence", 0.5)
            confidence = float(raw_conf if isinstance(raw_conf, (int, float)) else 0.5)
            confidence_bonus = confidence * 0.5
            # Pinned boost
            pinned = row.get("pinned_at") is not None
            pinned_boost = 2.0 if pinned else 0.0
            combined = (
                bm25_weight * norm_bm25
                + semantic_weight * semantic_score
                + recency_bonus * 0.15
                + confidence_bonus
                + pinned_boost
            )
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
        self, workspace_id: str, query: str, limit: int, include_archived: bool = False,
    ) -> list[dict[str, object]]:
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
                (workspace_id, query, limit),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

    def _fts_only_search(
        self, workspace_id: str, query: str, limit: int, include_archived: bool = False,
    ) -> list[dict[str, object]]:
        from .retrieval import MemoryRetriever
        return MemoryRetriever(self._db).search(workspace_id, query, limit, include_archived)

    def _get_embedding(self, memory_id: str) -> bytes | None:
        cur = self._db.connection.execute(
            "SELECT embedding FROM memory_embeddings WHERE memory_id = ?",
            (memory_id,),
        )
        row = cur.fetchone()
        return row["embedding"] if row else None
