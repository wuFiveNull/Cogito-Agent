from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cogito_agent.context import ContextEngine
from cogito_agent.embedding.interface import EmbeddingProvider
from cogito_agent.embedding.service import MemoryEmbeddingIndexService
from cogito_agent.memory import MemoryApplicationService, MemoryRetriever
from cogito_agent.retrieval import MemoryRetrievalService
from cogito_agent.retrieval.dense import DenseMemoryRetriever
from cogito_agent.retrieval.fusion import CandidateFusion
from cogito_agent.retrieval.query import MemoryQueryBuilder
from cogito_agent.retrieval.resident import ResidentMemorySelector
from cogito_agent.retrieval.sparse import SparseMemoryRetriever
from cogito_agent.storage import Database


@dataclass
class ApplicationServices:
    db: Database
    embedding_provider: EmbeddingProvider | None
    embedding_index: MemoryEmbeddingIndexService | None
    memory_retrieval: MemoryRetrievalService
    memory_application: MemoryApplicationService
    memory_retriever_compat: MemoryRetriever
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
    from cogito_agent.embedding.service import create_embedding_provider_from_config as _make_provider
    from cogito_agent.governance import AuditLogger
    from cogito_agent.retrieval import MemoryRetrievalService
    from cogito_agent.retrieval.gate import RetrievalGate
    from cogito_agent.retrieval.service import create_retrieval_service

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
        w = retrieval_cfg.weights
        fusion = CandidateFusion(
            dense_weight=w.dense,
            sparse_weight=w.sparse,
            recency_weight=w.recency,
            confidence_weight=w.confidence,
            task_relevance_weight=w.task_relevance,
            type_priority_weight=w.type_priority,
            recency_half_life_days=retrieval_cfg.recency_half_life_days,
        )

    memory_retrieval = MemoryRetrievalService(
        db=db,
        provider=embedding_provider,
        sparse_retriever=sparse_retriever,
        dense_retriever=dense_retriever,
        fusion=fusion,
        retrieval_config=retrieval_cfg,
    )

    # 4. Compat layer (for legacy callers)
    memory_retriever_compat = MemoryRetriever(db, service=memory_retrieval)

    # 5. Memory application service (write operations)
    audit = AuditLogger(db)
    memory_application = MemoryApplicationService(
        db=db,
        embedding_index=embedding_index,
        audit=audit,
    )

    # 6. Context engine
    max_tokens = 4096
    if config is not None and hasattr(config, "dynamic_token_budget"):
        max_tokens = getattr(config, "dynamic_token_budget", 4096)
    context_engine = ContextEngine(total_token_budget=max_tokens)

    return ApplicationServices(
        db=db,
        embedding_provider=embedding_provider,
        embedding_index=embedding_index,
        memory_retrieval=memory_retrieval,
        memory_application=memory_application,
        memory_retriever_compat=memory_retriever_compat,
        context_engine=context_engine,
    )
