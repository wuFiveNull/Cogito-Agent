from __future__ import annotations

import enum
import heapq
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from cogito_agent.embedding.interface import EmbeddingProvider
from cogito_agent.storage import Database

logger = logging.getLogger(__name__)

_EMBEDDING_VERSION = "2"


class DenseHealthState(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"


@dataclass
class DenseRetrievalResult:
    candidates: list[dict[str, object]] = field(default_factory=list)
    health_state: DenseHealthState = DenseHealthState.DISABLED
    error_code: str = ""
    error_message: str = ""
    latency_ms: float = 0.0


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _unpack_embedding(data: bytes) -> list[float]:
    import struct
    return list(struct.unpack(f"{len(data) // 4}f", data))


class DenseMemoryRetriever:
    def __init__(self, db: Database, provider: EmbeddingProvider | None = None) -> None:
        self._db = db
        self._provider = provider

    @property
    def provider(self) -> EmbeddingProvider | None:
        return self._provider

    @provider.setter
    def provider(self, p: EmbeddingProvider | None) -> None:
        self._provider = p

    def search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 40,
        include_archived: bool = False,
    ) -> DenseRetrievalResult:
        import time
        t0 = time.time()
        result = DenseRetrievalResult()

        if self._provider is None:
            result.health_state = DenseHealthState.DISABLED
            result.error_code = "embedding_disabled"
            return result

        if not self._provider.is_semantic:
            result.health_state = DenseHealthState.DISABLED
            result.error_code = "embedding_not_semantic"
            return result

        try:
            query_vec = self._provider.embed_text(query)
        except Exception as e:
            result.health_state = DenseHealthState.DEGRADED
            result.error_code = self._classify_error(e)
            result.error_message = str(e)[:200]
            result.latency_ms = (time.time() - t0) * 1000
            return result

        try:
            candidates = self._load_workspace_vectors(workspace_id, include_archived)
        except Exception as e:
            result.health_state = DenseHealthState.DEGRADED
            result.error_code = "db_load_failed"
            result.error_message = str(e)[:200]
            result.latency_ms = (time.time() - t0) * 1000
            return result

        if not candidates:
            result.health_state = DenseHealthState.HEALTHY
            result.candidates = []
            result.latency_ms = (time.time() - t0) * 1000
            return result

        scored: list[tuple[float, int, dict[str, object]]] = []
        for i, (mid, doc_vec) in enumerate(candidates):
            sim = _cosine_similarity(query_vec, doc_vec)
            sim = max(0.0, sim)
            scored.append((-sim, i, {
                "id": mid,
                "memory_id": mid,
                "dense_score": sim,
                "dense_rank": 0,
                "_model_name": self._provider.model_name,
                "_embedding_version": _EMBEDDING_VERSION,
            }))

        top_n = heapq.nsmallest(limit, scored)
        top_n.sort(key=lambda x: x[0])
        dense_results: list[dict[str, object]] = []
        for rank, (neg_sim, _, entry) in enumerate(top_n):
            entry["dense_rank"] = rank + 1
            mid = str(entry["memory_id"])
            mem_row = self._db.connection.execute(
                "SELECT * FROM memories WHERE id = ? AND workspace_id = ? AND deleted_at IS NULL",
                (mid, workspace_id),
            ).fetchone()
            if mem_row:
                mem = dict(mem_row)
                mem["dense_score"] = entry["dense_score"]
                mem["dense_rank"] = entry["dense_rank"]

                dense_results.append(mem)

        result.health_state = DenseHealthState.HEALTHY
        result.candidates = dense_results
        result.latency_ms = (time.time() - t0) * 1000
        return result

    @staticmethod
    def _classify_error(e: Exception) -> str:
        from cogito_agent.embedding.exceptions import (
            EmbeddingAPIError,
            EmbeddingAuthenticationError,
            EmbeddingDimensionMismatchError,
            EmbeddingRateLimitError,
            EmbeddingResponseError,
            EmbeddingTimeoutError,
        )
        if isinstance(e, EmbeddingAuthenticationError):
            return "embedding_auth_failed"
        if isinstance(e, EmbeddingRateLimitError):
            return "embedding_rate_limited"
        if isinstance(e, EmbeddingTimeoutError):
            return "embedding_timeout"
        if isinstance(e, EmbeddingDimensionMismatchError):
            return "embedding_dimension_mismatch"
        if isinstance(e, EmbeddingResponseError):
            return "embedding_invalid_response"
        if isinstance(e, EmbeddingAPIError):
            code = getattr(e, "status_code", 0)
            if code == 403:
                return "embedding_forbidden"
            return "embedding_api_error"
        msg = str(e).lower()
        if "connect" in msg or "connection" in msg:
            return "embedding_connection_failed"
        return "embedding_internal_error"

    def _embed_query(self, query: str) -> list[float] | None:
        if not self._provider:
            return None
        try:
            return self._provider.embed_text(query)
        except Exception as e:
            logger.warning("Query embedding failed: %s", e)
            return None

    def _load_workspace_vectors(
        self, workspace_id: str, include_archived: bool,
    ) -> list[tuple[str, list[float]]]:
        if not self._provider:
            return []

        archived_clause = "" if include_archived else " AND m.archived_at IS NULL"

        try:
            rows = self._db.connection.execute(
                "SELECT me.memory_id, me.embedding"
                " FROM memory_embeddings_v2 me"
                " JOIN memories m ON me.memory_id = m.id"
                " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
                + archived_clause
                + " AND me.status = 'ready'"
                " AND me.provider_name = ? AND me.model_name = ?"
                " AND me.embedding_version = ?"
                " AND me.dimension = ?",
                (
                    workspace_id,
                    self._provider.provider_name,
                    self._provider.model_name,
                    _EMBEDDING_VERSION,
                    self._provider.dimension,
                ),
            ).fetchall()
        except Exception as e:
            logger.warning("Failed to load workspace vectors: %s", e)
            return []

        result: list[tuple[str, list[float]]] = []
        for row in rows:
            mid = str(row["memory_id"])
            blob = row["embedding"]
            if not blob or not isinstance(blob, bytes) or len(blob) < 4:
                continue
            try:
                vec = _unpack_embedding(blob)
                if len(vec) != self._provider.dimension:
                    continue
                result.append((mid, vec))
            except Exception:
                continue

        return result

    def has_ready_embeddings(self, workspace_id: str) -> bool:
        if not self._provider:
            return False
        try:
            cur = self._db.connection.execute(
                "SELECT 1 FROM memory_embeddings_v2 me"
                " JOIN memories m ON me.memory_id = m.id"
                " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
                " AND me.status = 'ready'"
                " AND me.provider_name = ? AND me.model_name = ?"
                " AND me.embedding_version = ?"
                " LIMIT 1",
                (workspace_id, self._provider.provider_name,
                 self._provider.model_name, _EMBEDDING_VERSION),
            )
            return cur.fetchone() is not None
        except Exception:
            return False
