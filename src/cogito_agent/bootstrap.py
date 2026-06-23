from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cogito_agent.context import ContextEngine
from cogito_agent.embedding.interface import EmbeddingProvider
from cogito_agent.embedding.service import MemoryEmbeddingIndexService
from cogito_agent.memory import MemoryApplicationService
from cogito_agent.retrieval import MemoryRetrievalService
from cogito_agent.retrieval.dense import DenseMemoryRetriever
from cogito_agent.retrieval.fusion import CandidateFusion
from cogito_agent.retrieval.sparse import SparseMemoryRetriever
from cogito_agent.storage import Database
from cogito_agent.storage.context_sink import SqliteContextTraceSink


@dataclass
class ApplicationServices:
    db: Database
    embedding_provider: EmbeddingProvider | None
    embedding_index: MemoryEmbeddingIndexService | None
    memory_retrieval: MemoryRetrievalService
    memory_application: MemoryApplicationService
    context_engine: ContextEngine


def build_application_services(
    db: Database,
    config: Any,
    secrets_provider: Any = None,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> ApplicationServices:
    """Unified composition root for all application services.

    Every caller (API, CLI, daemon) must use this factory so that
    the HTTP client, secrets, config, and providers are wired exactly once.
    """
    from cogito_agent.embedding.service import (
        create_embedding_provider_from_config as _make_provider,
    )
    from cogito_agent.governance import AuditLogger

    # 1. Embedding provider
    if embedding_provider is None and config is not None:
        emb_cfg = getattr(config, "embedding", None)
        if emb_cfg is not None:
            embedding_provider = _make_provider(emb_cfg, secrets_provider=secrets_provider)

    # 2. Embedding index service
    embedding_index: MemoryEmbeddingIndexService | None = None
    if embedding_provider is not None:
        embedding_index = MemoryEmbeddingIndexService(db, embedding_provider)

    # 3. Retrieval service (sparse + dense + fusion + gate)
    retrieval_cfg = getattr(config, "retrieval", None) if config is not None else None

    sparse_retriever = SparseMemoryRetriever(db)
    dense_retriever = DenseMemoryRetriever(db, embedding_provider)

    fusion = None
    if retrieval_cfg is not None:
        rrf_cfg = retrieval_cfg.rrf
        fusion = CandidateFusion(
            rrf_k=rrf_cfg.k,
            keyword_weight=rrf_cfg.keyword_weight,
            recency_half_life_days=retrieval_cfg.recency_half_life_days,
            hotness_alpha=rrf_cfg.hotness_alpha,
        )

    memory_retrieval = MemoryRetrievalService(
        db=db,
        provider=embedding_provider,
        sparse_retriever=sparse_retriever,
        dense_retriever=dense_retriever,
        fusion=fusion,
        retrieval_config=retrieval_cfg,
    )

    # 4. Memory application service (write operations)
    audit = AuditLogger(db)
    memory_application = MemoryApplicationService(
        db=db,
        embedding_index=embedding_index,
        audit=audit,
    )

    # 5. Context engine
    max_tokens = 4096
    if retrieval_cfg is not None:
        max_tokens = getattr(retrieval_cfg, "dynamic_token_budget", 4096)
    context_engine = ContextEngine(
        total_token_budget=max_tokens,
        trace_sink=SqliteContextTraceSink(db),
    )

    return ApplicationServices(
        db=db,
        embedding_provider=embedding_provider,
        embedding_index=embedding_index,
        memory_retrieval=memory_retrieval,
        memory_application=memory_application,
        context_engine=context_engine,
    )
