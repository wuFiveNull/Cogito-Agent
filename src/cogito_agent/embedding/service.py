from __future__ import annotations

import hashlib
import logging
import struct
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database

from .interface import EmbeddingProvider

logger = logging.getLogger(__name__)

_EMBEDDING_VERSION = "2"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_embedding(data: bytes) -> list[float]:
    return list(struct.unpack(f"{len(data) // 4}f", data))


class MemoryEmbeddingIndexService:
    def __init__(
        self,
        db: Database,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self._db = db
        self._provider = provider

    @property
    def provider(self) -> EmbeddingProvider | None:
        return self._provider

    @provider.setter
    def provider(self, p: EmbeddingProvider | None) -> None:
        self._provider = p

    def index_memory(self, memory_id: str, text: str) -> bool:
        if not self._provider:
            return False
        if not text.strip():
            return False
        content_hash = _content_hash(text)
        existing = self._get_existing_embedding(memory_id)
        if existing:
            existing_hash = existing.get("content_hash", "")
            existing_version = existing.get("embedding_version", "")
            existing_model = existing.get("model_name", "")
            existing_provider = existing.get("provider_name", "")
            if (
                existing_hash == content_hash
                and existing_version == _EMBEDDING_VERSION
                and existing_model == self._provider.model_name
                and existing_provider == self._provider.provider_name
                and existing.get("status") == "ready"
            ):
                return True

        try:
            vec = self._provider.embed_text(text)
        except Exception as e:
            self._upsert_embedding(
                memory_id=memory_id,
                workspace_id="",
                content_hash=content_hash,
                status="failed",
                error_code=str(e)[:200],
            )
            logger.warning("Embedding failed for memory %s: %s", memory_id, e)
            return False

        self._upsert_embedding(
            memory_id=memory_id,
            workspace_id="",
            content_hash=content_hash,
            status="ready",
            embedding=vec,
        )
        return True

    def index_memories(self, memory_ids: Sequence[str], batch_size: int = 32) -> dict[str, bool]:
        results: dict[str, bool] = {}
        batch: list[tuple[str, str, str]] = []
        for mid in memory_ids:
            row = self._db.connection.execute(
                "SELECT text FROM memories WHERE id = ? AND deleted_at IS NULL",
                (mid,),
            ).fetchone()
            if row is None:
                results[mid] = False
                continue
            batch.append((mid, str(row["text"]), _content_hash(str(row["text"]))))
        for start in range(0, len(batch), batch_size):
            chunk = batch[start : start + batch_size]
            try:
                texts = [item[1] for item in chunk]
                if self._provider:
                    vectors = self._provider.embed_batch(texts)
                else:
                    for item in chunk:
                        results[item[0]] = False
                    continue
            except Exception:
                for item in chunk:
                    results[item[0]] = False
                    self._upsert_embedding(item[0], "", item[2], "failed")
                continue
            if len(vectors) != len(chunk):
                for item in chunk:
                    results[item[0]] = False
                continue
            for item, vec in zip(chunk, vectors):
                results[item[0]] = True
                self._upsert_embedding(item[0], "", item[2], "ready", embedding=vec)
        return results

    def rebuild_workspace(
        self,
        workspace_id: str,
        *,
        force: bool = False,
        batch_size: int = 32,
    ) -> dict[str, Any]:
        if not self._provider:
            return {"status": "error", "message": "No embedding provider configured"}
        rows = self._db.connection.execute(
            "SELECT id, text FROM memories WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,),
        ).fetchall()
        total = len(rows)
        indexed = 0
        failed = 0
        skipped = 0

        pending: list[tuple[str, str, str]] = []
        for row in rows:
            mid = str(row["id"])
            text = str(row["text"])
            content_hash = _content_hash(text)
            if not force:
                existing = self._get_existing_embedding(mid)
                if (
                    existing
                    and existing.get("status") == "ready"
                    and existing.get("embedding_version") == _EMBEDDING_VERSION
                    and existing.get("model_name") == self._provider.model_name
                    and existing.get("content_hash") == content_hash
                ):
                    skipped += 1
                    continue
            pending.append((mid, text, content_hash))

        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            texts = [item[1] for item in batch]
            try:
                vectors = self._provider.embed_batch(texts)
            except Exception as e:
                logger.warning("Batch embedding failed for %d items: %s", len(batch), e)
                for item in batch:
                    self._upsert_embedding(
                        item[0], workspace_id, item[2], "failed", error_code=str(e)[:200]
                    )
                    failed += 1
                continue

            if len(vectors) != len(batch):
                logger.warning(
                    "Batch response count %d != input count %d", len(vectors), len(batch)
                )
                for item in batch:
                    self._upsert_embedding(
                        item[0],
                        workspace_id,
                        item[2],
                        "failed",
                        error_code="response_count_mismatch",
                    )
                    failed += 1
                continue

            for item, vec in zip(batch, vectors):
                self._upsert_embedding(item[0], workspace_id, item[2], "ready", embedding=vec)
                indexed += 1

        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "total": total,
            "indexed": indexed,
            "failed": failed,
            "skipped": skipped,
        }

    def mark_stale(self, memory_id: str) -> None:
        self._db.connection.execute(
            "UPDATE memory_embeddings_v2 SET status = 'stale', updated_at = ? WHERE memory_id = ?",
            (datetime.now(UTC).isoformat(), memory_id),
        )
        self._db.connection.commit()

    def delete_or_deactivate(self, memory_id: str) -> None:
        self._db.connection.execute(
            "DELETE FROM memory_embeddings_v2 WHERE memory_id = ?",
            (memory_id,),
        )
        self._db.connection.commit()

    def status(self, workspace_id: str) -> dict[str, Any]:
        if not self._provider:
            return {
                "provider": "none",
                "model": "none",
                "dimension": 0,
                "ready": 0,
                "pending": 0,
                "failed": 0,
                "stale": 0,
                "total_memories": 0,
                "coverage_pct": 0.0,
            }

        total = self._db.connection.execute(
            "SELECT COUNT(*) FROM memories WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,),
        ).fetchone()[0]

        counts = self._db.connection.execute(
            "SELECT status, COUNT(*) as cnt FROM memory_embeddings_v2 me"
            " JOIN memories m ON me.memory_id = m.id"
            " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
            " AND me.provider_name = ? AND me.model_name = ?"
            " AND me.embedding_version = ?"
            " GROUP BY me.status",
            (
                workspace_id,
                self._provider.provider_name,
                self._provider.model_name,
                _EMBEDDING_VERSION,
            ),
        ).fetchall()

        status_counts = {row["status"]: row["cnt"] for row in counts}
        ready = status_counts.get("ready", 0)
        coverage = (ready / total * 100.0) if total > 0 else 0.0

        return {
            "provider": self._provider.provider_name,
            "model": self._provider.model_name,
            "dimension": self._provider.dimension,
            "is_semantic": self._provider.is_semantic,
            "embedding_version": _EMBEDDING_VERSION,
            "ready": ready,
            "pending": status_counts.get("pending", 0),
            "failed": status_counts.get("failed", 0),
            "stale": status_counts.get("stale", 0),
            "total_memories": total,
            "coverage_pct": round(coverage, 1),
        }

    def retry_failed(self, workspace_id: str, batch_size: int = 32) -> dict[str, Any]:
        if not self._provider:
            return {"status": "error", "message": "No embedding provider"}
        rows = self._db.connection.execute(
            "SELECT me.memory_id, m.text"
            " FROM memory_embeddings_v2 me"
            " JOIN memories m ON me.memory_id = m.id"
            " WHERE m.workspace_id = ? AND m.deleted_at IS NULL"
            " AND me.status = 'failed'"
            " AND me.provider_name = ? AND me.model_name = ?"
            " AND me.embedding_version = ?",
            (
                workspace_id,
                self._provider.provider_name,
                self._provider.model_name,
                _EMBEDDING_VERSION,
            ),
        ).fetchall()
        items = [(str(r["memory_id"]), str(r["text"]), _content_hash(str(r["text"]))) for r in rows]
        succeeded = 0
        failed = 0
        for start in range(0, len(items), batch_size):
            chunk = items[start : start + batch_size]
            try:
                vectors = self._provider.embed_batch([item[1] for item in chunk])
            except Exception:
                for item in chunk:
                    self._upsert_embedding(item[0], workspace_id, item[2], "failed")
                    failed += 1
                continue
            if len(vectors) != len(chunk):
                for item in chunk:
                    failed += 1
                continue
            for item, vec in zip(chunk, vectors):
                self._upsert_embedding(item[0], workspace_id, item[2], "ready", embedding=vec)
                succeeded += 1
        return {"status": "ok", "succeeded": succeeded, "failed": failed}

    def purge_stale(self, workspace_id: str) -> int:
        cur = self._db.connection.execute(
            "DELETE FROM memory_embeddings_v2 WHERE memory_id IN"
            " (SELECT id FROM memories WHERE workspace_id = ? AND deleted_at IS NULL)"
            " AND status = 'stale'",
            (workspace_id,),
        )
        self._db.connection.commit()
        return cur.rowcount

    def _upsert_embedding(
        self,
        memory_id: str,
        workspace_id: str,
        content_hash: str,
        status: str,
        embedding: list[float] | None = None,
        error_code: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        if embedding is not None:
            blob = _pack_embedding(embedding)
        else:
            blob = b""

        ws_id = workspace_id
        if not ws_id:
            row = self._db.connection.execute(
                "SELECT workspace_id FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row:
                ws_id = str(row["workspace_id"])

        self._db.connection.execute(
            "INSERT OR REPLACE INTO memory_embeddings_v2"
            " (memory_id, workspace_id, provider_name, model_name, dimension,"
            "  embedding, content_hash, embedding_version, status, error_code,"
            "  created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                ws_id,
                self._provider.provider_name if self._provider else "",
                self._provider.model_name if self._provider else "",
                self._provider.dimension if self._provider else 0,
                blob,
                content_hash,
                _EMBEDDING_VERSION,
                status,
                error_code,
                now,
                now,
            ),
        )
        self._db.connection.commit()

    def _get_existing_embedding(self, memory_id: str) -> dict[str, Any] | None:
        cur = self._db.connection.execute(
            "SELECT * FROM memory_embeddings_v2 WHERE memory_id = ?",
            (memory_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def health_check(self) -> dict[str, Any]:
        if not self._provider:
            return {"healthy": False, "message": "No embedding provider configured"}
        health = self._provider.health_check()
        return {
            "healthy": health.healthy,
            "provider": health.provider_name,
            "model": health.model_name,
            "dimension": health.dimension,
            "is_semantic": health.is_semantic,
            "error": health.error_message if not health.healthy else "",
        }


def create_embedding_provider_from_config(
    cfg: Any,
    secrets_provider: Any = None,
) -> EmbeddingProvider | None:
    from cogito_agent.config.loader import EmbeddingSettings

    if isinstance(cfg, dict):
        es = EmbeddingSettings(**cfg)
    elif hasattr(cfg, "embedding"):
        es = cfg.embedding
    else:
        es = cfg

    provider_type = es.provider

    api_key = es.api_key if es.api_key else ""
    if not api_key and secrets_provider and es.api_key_secret_name:
        try:
            api_key = secrets_provider.get(es.api_key_secret_name) or ""
        except Exception:
            api_key = ""
    if not api_key and es.api_key_env:
        import os

        api_key = os.environ.get(es.api_key_env, "")

    if provider_type == "openai_compatible":
        from .openai_compatible import OpenAICompatibleEmbeddingProvider

        return OpenAICompatibleEmbeddingProvider(
            base_url=es.base_url,
            model=es.model,
            api_key=api_key,
            expected_dimension=es.expected_dimension,
            encoding_format=es.encoding_format,
            timeout_seconds=es.timeout_seconds,
            connect_timeout_seconds=es.connect_timeout_seconds,
            max_retries=es.max_retries,
            batch_size=es.batch_size,
            normalize=es.normalize,
            verify_norm=es.verify_norm,
            max_input_tokens=es.max_input_tokens,
        )
    elif provider_type == "local_sentence_transformer":
        from .local import LocalSentenceTransformerEmbeddingProvider

        return LocalSentenceTransformerEmbeddingProvider(model_name=es.model)
    elif provider_type == "mock":
        from .mock import MockEmbeddingProvider

        return MockEmbeddingProvider(dimension=es.expected_dimension or 384)
    elif provider_type == "disabled" or provider_type == "none":
        return None
    else:
        raise ValueError(f"Unknown embedding provider: {provider_type}")
