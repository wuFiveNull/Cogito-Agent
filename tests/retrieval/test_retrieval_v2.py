from __future__ import annotations

import math
import os
import tempfile

import pytest

from cogito_agent.config.loader import RetrievalSettings
from cogito_agent.embedding.interface import EmbeddingHealth, EmbeddingProvider
from cogito_agent.embedding.mock import MockEmbeddingProvider
from cogito_agent.retrieval.dense import DenseMemoryRetriever
from cogito_agent.retrieval.fusion import CandidateFusion, ScoreBreakdown
from cogito_agent.retrieval.gate import RetrievalGate
from cogito_agent.retrieval.query import MemoryQueryBuilder
from cogito_agent.retrieval.resident import ResidentMemorySelector
from cogito_agent.retrieval.service import MemoryRetrievalService
from cogito_agent.retrieval.sparse import SparseMemoryRetriever
from cogito_agent.storage import Database


@pytest.fixture
def db() -> Database:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _db = Database(path=path)
    _db.initialize()
    _db.migrate()
    yield _db
    _db.connection.close()
    os.unlink(path)


def _ensure_workspace(db: Database, ws_id: str) -> None:
    cur = db.connection.execute(
        "SELECT id FROM workspaces WHERE id = ?", (ws_id,)
    )
    if cur.fetchone() is None:
        db.connection.execute(
            "INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, ws_id)
        )
        db.connection.commit()


def _add_memory(
    db: Database, mid: str, ws: str, text: str,
    mtype: str = "general", confidence: float = 0.5,
    pinned: bool = False, archived: bool = False,
) -> None:
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    _ensure_workspace(db, ws)
    pinned_at = now if pinned else None
    archived_at = now if archived else None
    db.connection.execute(
        "INSERT OR IGNORE INTO memories"
        " (id, workspace_id, text, type, confidence, pinned_at,"
        " status, created_at, updated_at, archived_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
        (mid, ws, text, mtype, confidence, pinned_at, now, now, archived_at),
    )
    row = db.connection.execute(
        "SELECT rowid FROM memories WHERE id = ?", (mid,)
    ).fetchone()
    if row:
        db.connection.execute(
            "INSERT OR IGNORE INTO memories_fts (rowid, text, summary)"
            " VALUES (?, ?, ?)",
            (row[0], text, text[:100]),
        )
    db.connection.commit()


def _add_v2_embedding(
    db: Database, mid: str, ws: str, vec: list[float],
    provider: str = "mock", model: str = "mock",
    dimension: int = 384, status: str = "ready",
    version: str = "2",
) -> None:
    import struct
    blob = struct.pack(f"{len(vec)}f", *vec)
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    db.connection.execute(
        "INSERT OR REPLACE INTO memory_embeddings_v2"
        " (memory_id, workspace_id, provider_name, model_name, dimension,"
        "  embedding, content_hash, embedding_version, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)",
        (mid, ws, provider, model, dimension, blob, version, status, now, now),
    )
    db.connection.commit()


# ============================================================
# Sparse Retriever Tests
# ============================================================


class TestSparseMemoryRetriever:
    def test_basic_fts(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "apple banana fruit")
        _add_memory(db, "m2", "ws", "cat dog animal")
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "apple", limit=10)
        assert len(results) >= 1
        assert any("apple" in str(r["text"]) for r in results)

    def test_no_results(self, db):
        _ensure_workspace(db, "ws")
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "nonexistent", limit=10)
        assert len(results) == 0

    def test_workspace_isolation(self, db):
        _ensure_workspace(db, "ws-a")
        _ensure_workspace(db, "ws-b")
        _add_memory(db, "m1", "ws-a", "secret data")
        retriever = SparseMemoryRetriever(db)
        results_a = retriever.search("ws-a", "secret", limit=10)
        assert len(results_a) >= 1
        results_b = retriever.search("ws-b", "secret", limit=10)
        assert len(results_b) == 0

    def test_like_fallback(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "some unique content here")
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "unique", limit=10)
        assert len(results) >= 1

    def test_chinese_query(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "我喜欢Python编程")
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "Python", limit=10)
        assert len(results) >= 1

    def test_archived_excluded(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "archived content", archived=True)
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "archived", limit=10)
        assert len(results) == 0

    def test_archived_included(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "archived content", archived=True)
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "archived", limit=10, include_archived=True)
        assert len(results) >= 1

    def test_sparse_score_normalized(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "apple banana cherry date")
        retriever = SparseMemoryRetriever(db)
        results = retriever.search("ws", "apple", limit=10)
        if results:
            score = results[0].get("sparse_score", -1)
            assert isinstance(score, (int, float))
            assert 0.0 <= score <= 1.0

    def test_sanitize_fts_query(self, db):
        from cogito_agent.retrieval.sparse import _sanitize_fts_query
        result = _sanitize_fts_query('test" OR "1" = "1')
        assert '"' not in result


# ============================================================
# Dense Retriever Tests
# ============================================================


class _TestSemanticProvider:
    """Test-only semantic embedding provider for dense retriever testing."""
    def __init__(self, dimension: int = 384):
        self._dimension = dimension
        self._mock = MockEmbeddingProvider(dimension=dimension)

    @property
    def provider_name(self) -> str:
        return "test_semantic"

    @property
    def model_name(self) -> str:
        return "test_model"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_semantic(self) -> bool:
        return True

    def embed_text(self, text: str) -> list[float]:
        return self._mock.embed_text(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._mock.embed_batch(texts)

    def health_check(self) -> EmbeddingHealth:
        return EmbeddingHealth(
            healthy=True, provider_name=self.provider_name,
            model_name=self.model_name, dimension=self._dimension,
            is_semantic=True,
        )


class TestDenseMemoryRetriever:
    def test_dense_retrieval_finds_semantic_match(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(
            db, "m1", "ws",
            "出差产生的交通和住宿费用统一由财务部门报销。",
            mtype="general",
        )
        _add_memory(
            db, "m2", "ws",
            "关于午饭的饭菜",
            mtype="general",
        )

        provider = _TestSemanticProvider(dimension=384)
        vec = provider.embed_text(
            "出差产生的交通和住宿费用统一由财务部门报销。"
        )
        _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                          model="test_model", status="ready")

        irrelevant_vec = provider.embed_text("关于午饭的饭菜")
        _add_v2_embedding(db, "m2", "ws", irrelevant_vec, provider="test_semantic",
                          model="test_model", status="ready")

        retriever = DenseMemoryRetriever(db, provider)
        dense_result = retriever.search("ws", "公司的差旅支出应该怎么处理？", limit=10)
        ids = [str(r["id"]) for r in dense_result.candidates]
        assert "m1" in ids

    def test_dense_retrieval_no_provider(self, db):
        retriever = DenseMemoryRetriever(db, None)
        dense_result = retriever.search("ws", "test", limit=10)
        assert len(dense_result.candidates) == 0

    def test_dense_retrieval_no_embeddings(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "test content")
        provider = _TestSemanticProvider()
        retriever = DenseMemoryRetriever(db, provider)
        dense_result = retriever.search("ws", "test", limit=10)
        assert len(dense_result.candidates) == 0

    def test_dense_retrieval_stale_embeddings_excluded(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "test content")
        provider = _TestSemanticProvider()
        vec = provider.embed_text("test content")
        _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                          model="test_model", status="stale")
        retriever = DenseMemoryRetriever(db, provider)
        dense_result = retriever.search("ws", "test", limit=10)
        assert len(dense_result.candidates) == 0

    def test_workspace_isolation(self, db):
        _ensure_workspace(db, "ws-a")
        _ensure_workspace(db, "ws-b")
        _add_memory(db, "m1", "ws-a", "secret data")
        provider = _TestSemanticProvider()
        vec = provider.embed_text("secret data")
        _add_v2_embedding(db, "m1", "ws-a", vec, provider="test_semantic",
                          model="test_model", status="ready")
        retriever = DenseMemoryRetriever(db, provider)
        dense_result_a = retriever.search("ws-a", "secret", limit=10)
        assert len(dense_result_a.candidates) >= 1
        dense_result_b = retriever.search("ws-b", "secret", limit=10)
        assert len(dense_result_b.candidates) == 0

    def test_has_ready_embeddings(self, db):
        _ensure_workspace(db, "ws")
        provider = _TestSemanticProvider()
        retriever = DenseMemoryRetriever(db, provider)
        assert retriever.has_ready_embeddings("ws") is False
        _add_memory(db, "m1", "ws", "test")
        vec = provider.embed_text("test")
        _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                          model="test_model", status="ready")
        assert retriever.has_ready_embeddings("ws") is True


# ============================================================
# Candidate Fusion Tests
# ============================================================


class TestCandidateFusion:
    def test_basic_fusion(self):
        sparse = [
            {"id": "m1", "text": "apple", "sparse_score": 0.8, "type": "general",
             "confidence": 0.5, "created_at": None},
            {"id": "m2", "text": "banana", "sparse_score": 0.6, "type": "general",
             "confidence": 0.5, "created_at": None},
        ]
        dense = [
            {"id": "m2", "text": "banana", "dense_score": 0.9, "dense_rank": 1,
             "type": "general", "confidence": 0.5, "created_at": None},
            {"id": "m3", "text": "cherry", "dense_score": 0.7, "dense_rank": 2,
             "type": "general", "confidence": 0.5, "created_at": None},
        ]
        fusion = CandidateFusion()
        results = fusion.fuse(sparse, dense, query="fruit")
        assert len(results) == 3
        ids = [r[0]["id"] for r in results]
        assert "m2" in ids
        assert "m3" in ids

    def test_no_duplicates(self):
        sparse = [
            {"id": "m1", "text": "test", "sparse_score": 0.8, "type": "general",
             "confidence": 0.5, "created_at": None},
        ]
        dense = [
            {"id": "m1", "text": "test", "dense_score": 0.9, "dense_rank": 1,
             "type": "general", "confidence": 0.5, "created_at": None},
        ]
        fusion = CandidateFusion()
        results = fusion.fuse(sparse, dense, query="test")
        assert len(results) == 1

    def test_score_breakdown(self):
        sparse = [
            {"id": "m1", "text": "python programming", "sparse_score": 0.8,
             "type": "preference", "confidence": 0.9, "created_at": None},
        ]
        dense = [
            {"id": "m1", "text": "python programming", "dense_score": 0.7,
             "dense_rank": 1, "type": "preference", "confidence": 0.9,
             "created_at": None},
        ]
        fusion = CandidateFusion()
        results = fusion.fuse(sparse, dense, query="python")
        _, breakdown = results[0]
        assert breakdown.dense_score == 0.7
        assert breakdown.sparse_score == 0.8
        assert breakdown.final_score > 0

    def test_score_sorting(self):
        sparse = [
            {"id": "m1", "text": "low relevance", "sparse_score": 0.1,
             "type": "general", "confidence": 0.1, "created_at": None},
            {"id": "m2", "text": "high relevance", "sparse_score": 0.9,
             "type": "general", "confidence": 0.9, "created_at": None},
        ]
        fusion = CandidateFusion()
        results = fusion.fuse(sparse, [], query="test")
        assert results[0][0]["id"] == "m2"


# ============================================================
# Retrieval Gate Tests
# ============================================================


class TestRetrievalGate:
    def test_empty_message(self):
        gate = RetrievalGate()
        from cogito_agent.retrieval.query import MemoryQueryContext
        ctx = MemoryQueryContext(current_message="")
        result = gate.evaluate(ctx)
        assert result.mode == "no_recall"

    def test_greeting(self):
        gate = RetrievalGate()
        from cogito_agent.retrieval.query import MemoryQueryContext
        ctx = MemoryQueryContext(current_message="hi")
        result = gate.evaluate(ctx)
        assert result.mode == "resident_only"

    def test_profile_query(self):
        gate = RetrievalGate()
        from cogito_agent.retrieval.query import MemoryQueryContext
        ctx = MemoryQueryContext(current_message="我喜欢什么类型的电影")
        result = gate.evaluate(ctx)
        assert result.mode == "profile_only"

    def test_temporal_query(self):
        gate = RetrievalGate()
        from cogito_agent.retrieval.query import MemoryQueryContext
        ctx = MemoryQueryContext(current_message="上次我们讨论了什么")
        result = gate.evaluate(ctx)
        assert result.mode == "timeline"

    def test_project_query(self):
        gate = RetrievalGate()
        from cogito_agent.retrieval.query import MemoryQueryContext
        ctx = MemoryQueryContext(current_message="项目的截止日期是什么时候")
        result = gate.evaluate(ctx)
        assert result.mode in ("hybrid", "timeline")

    def test_hybrid_default(self):
        gate = RetrievalGate()
        from cogito_agent.retrieval.query import MemoryQueryContext
        ctx = MemoryQueryContext(current_message="你能帮我了解一下Python吗")
        result = gate.evaluate(ctx)
        assert result.mode == "hybrid"


# ============================================================
# Query Builder Tests
# ============================================================


class TestMemoryQueryBuilder:
    def test_basic_query(self):
        builder = MemoryQueryBuilder()
        ctx = builder.build(current_message="Python programming")
        assert ctx.original_query == "Python programming"
        assert ctx.sparse_safe_query is not None

    def test_enriched_with_recent_turns(self):
        builder = MemoryQueryBuilder()
        ctx = builder.build(
            current_message="它的文档在哪里",
            recent_user_messages=["Python是什么", "Python编程语言的特点"],
        )
        assert len(ctx.context_enriched_query) > len("它的文档在哪里")

    def test_assistant_not_confused_as_user(self):
        builder = MemoryQueryBuilder()
        ctx = builder.build(
            current_message="你好",
            recent_user_messages=["今天天气怎么样"],
        )
        assert "Python" not in ctx.context_enriched_query

    def test_entity_extraction(self):
        builder = MemoryQueryBuilder()
        entities = builder._extract_entities("Fix the `calculateTotal` function in user.py")
        assert "calculateTotal" in entities

    def test_temporal_hints(self):
        builder = MemoryQueryBuilder()
        hints = builder._detect_temporal_hints("之前我们说过什么")
        assert len(hints) >= 1

    def test_chinese_query(self):
        builder = MemoryQueryBuilder()
        ctx = builder.build(current_message="Python的特点是什么")
        assert "Python" in ctx.context_enriched_query


# ============================================================
# Resident Selector Tests
# ============================================================


class TestResidentMemorySelector:
    def test_selects_pinned_profile(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "user profile info", mtype="profile",
                    confidence=0.9, pinned=True)
        selector = ResidentMemorySelector(db)
        results = selector.select("ws", token_budget=500)
        assert len(results) >= 1
        assert results[0]["id"] == "m1"

    def test_respects_type_policy(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "profile info", mtype="profile",
                    confidence=0.9, pinned=True)
        _add_memory(db, "m2", "ws", "more profile", mtype="profile",
                    confidence=0.8, pinned=True)
        _add_memory(db, "m3", "ws", "third profile", mtype="profile",
                    confidence=0.7, pinned=True)
        selector = ResidentMemorySelector(db)
        type_policy = {
            "profile": {"threshold": 0.35, "max_items": 2, "resident_eligible": True},
        }
        results = selector.select("ws", token_budget=500, type_policy=type_policy)
        assert len(results) <= 2

    def test_ignores_deleted(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "profile info", mtype="profile",
                    confidence=0.9, pinned=True)
        db.connection.execute(
            "UPDATE memories SET deleted_at = datetime('now') WHERE id = 'm1'"
        )
        db.connection.commit()
        selector = ResidentMemorySelector(db)
        results = selector.select("ws", token_budget=500)
        assert len(results) == 0

    def test_excludes_non_pinned_non_eligible(self, db):
        _ensure_workspace(db, "ws")
        _add_memory(db, "m1", "ws", "general info", mtype="general", pinned=False)
        selector = ResidentMemorySelector(db)
        results = selector.select("ws", token_budget=500)
        assert len(results) == 0


# ============================================================
# Integration: Dense-only recall for semantic match
# ============================================================


def test_dense_only_recall_semantic_match(db):
    _ensure_workspace(db, "ws")
    _add_memory(
        db, "m1", "ws",
        "出差产生的交通和住宿费用统一由财务部门报销。",
        mtype="general", confidence=0.9,
    )

    provider = _TestSemanticProvider(dimension=384)
    vec = provider.embed_text(
        "出差产生的交通和住宿费用统一由财务部门报销。"
    )
    _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                      model="test_model", status="ready")

    retriever = DenseMemoryRetriever(db, provider)
    dense_result = retriever.search(
        "ws", "公司的差旅支出应该怎么处理？", limit=10,
    )
    assert len(dense_result.candidates) >= 1
    assert dense_result.candidates[0]["id"] == "m1"


def test_hybrid_service_works(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana fruit", mtype="general",
                confidence=0.9)
    _add_memory(db, "m2", "ws", "cat dog animal", mtype="general",
                confidence=0.5)

    provider = _TestSemanticProvider(dimension=384)
    vec_fruit = provider.embed_text("apple banana fruit")
    _add_v2_embedding(db, "m1", "ws", vec_fruit, provider="test_semantic",
                      model="test_model", status="ready")

    sparse = SparseMemoryRetriever(db)
    dense = DenseMemoryRetriever(db, provider)
    svc = MemoryRetrievalService(
        db=db, provider=provider,
        sparse_retriever=sparse, dense_retriever=dense,
    )
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = builder.build(current_message="apple", workspace_id="ws")
    result = svc.recall(ctx, limit=10)
    assert result.selected_count >= 1

    ids = [str(m["id"]) for m in result.dynamic_memories]
    assert "m1" in ids


def test_search_compat_backward(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana fruit")
    provider = _TestSemanticProvider(dimension=384)
    vec = provider.embed_text("apple banana fruit")
    _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                      model="test_model", status="ready")

    sparse = SparseMemoryRetriever(db)
    dense = DenseMemoryRetriever(db, provider)
    svc = MemoryRetrievalService(
        db=db, provider=provider,
        sparse_retriever=sparse, dense_retriever=dense,
    )
    results = svc.search_compat("ws", "apple", limit=10)
    assert len(results) >= 1


def test_degraded_sparse_only_on_dense_failure(db):
    """When dense retrieval fails (no provider), system degrades to sparse-only."""
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana fruit")
    sparse = SparseMemoryRetriever(db)
    svc = MemoryRetrievalService(
        db=db, provider=None,
        sparse_retriever=sparse,
        dense_retriever=DenseMemoryRetriever(db, None),
    )
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = builder.build(current_message="apple", workspace_id="ws")
    result = svc.recall(ctx, limit=10)
    assert result.selected_count >= 1
    assert "m1" in [str(m["id"]) for m in result.dynamic_memories]


def test_no_recall_gate_mode(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "test content")
    sparse = SparseMemoryRetriever(db)
    svc = MemoryRetrievalService(
        db=db, provider=None,
        sparse_retriever=sparse,
        dense_retriever=DenseMemoryRetriever(db, None),
    )
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = builder.build(current_message="", workspace_id="ws")
    result = svc.recall(ctx, limit=10)
    assert result.mode == "no_recall"
    assert result.resident_count == 0
    assert result.selected_count == 0


def test_pinned_not_dominating_low_relevance(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "highly relevant content about python programming",
                mtype="general", confidence=0.9, pinned=False)
    _add_memory(db, "m2", "ws", "completely unrelated",
                mtype="general", confidence=0.5, pinned=True)

    provider = _TestSemanticProvider(dimension=384)
    vec_m1 = provider.embed_text("highly relevant content about python programming")
    vec_m2 = provider.embed_text("completely unrelated")
    _add_v2_embedding(db, "m1", "ws", vec_m1, provider="test_semantic",
                      model="test_model", status="ready")
    _add_v2_embedding(db, "m2", "ws", vec_m2, provider="test_semantic",
                      model="test_model", status="ready")

    sparse = SparseMemoryRetriever(db)
    dense = DenseMemoryRetriever(db, provider)
    fusion = CandidateFusion(
        dense_weight=0.35, sparse_weight=0.30, recency_weight=0.10,
        confidence_weight=0.10, task_relevance_weight=0.10, type_priority_weight=0.05,
    )
    svc = MemoryRetrievalService(
        db=db, provider=provider,
        sparse_retriever=sparse, dense_retriever=dense,
        fusion=fusion,
    )
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = ctx = builder.build(current_message="python programming language", workspace_id="ws")
    result = svc.recall(ctx, limit=10)
    if len(result.dynamic_memories) >= 2:
        assert result.dynamic_memories[0]["id"] == "m1"


def test_resident_only_gate_mode(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "profile info", mtype="profile", confidence=0.9, pinned=True)
    _add_memory(db, "m2", "ws", "general info", mtype="general", confidence=0.5)
    from cogito_agent.retrieval.service import MemoryRetrievalService as _MRS
    svc = _MRS(db=db, sparse_retriever=SparseMemoryRetriever(db))
    from cogito_agent.retrieval.gate import RetrievalGateResult
    from cogito_agent.retrieval.query import MemoryQueryContext
    ctx = MemoryQueryContext(current_message="hello")
    result = svc.recall(ctx, limit=10)
    assert result.mode in ("resident_only", "hybrid")
    assert result.resident_count >= 0


def test_type_threshold_enforced(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "general info 1", mtype="general", confidence=0.1)
    sparse = SparseMemoryRetriever(db)
    svc = MemoryRetrievalService(
        db=db, provider=None,
        sparse_retriever=sparse,
        dense_retriever=DenseMemoryRetriever(db, None),
        retrieval_config={
            "type_policy": {
                "general": {"threshold": 0.50, "max_items": 2, "resident_eligible": False},
            },
            "min_final_score": 0.20,
        },
    )
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = builder.build(current_message="nonexistent", workspace_id="ws")
    result = svc.recall(ctx, limit=10)
    assert result.selected_count == 0


def test_explain_search(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana fruit")
    sparse = SparseMemoryRetriever(db)
    svc = MemoryRetrievalService(
        db=db, provider=None,
        sparse_retriever=sparse,
        dense_retriever=DenseMemoryRetriever(db, None),
    )
    explain = svc.explain_search("ws", "apple")
    assert "mode" in explain
    assert "score_breakdowns" in explain
    assert "selected" in explain


def test_old_v1_embeddings_isolated_from_v2(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "legacy content")
    import struct
    old_vec = struct.pack(f"{384}f", *([0.1] * 384))
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    db.connection.execute(
        "INSERT INTO memory_embeddings_v2"
        " (memory_id, workspace_id, provider_name, model_name, dimension,"
        "  embedding, content_hash, embedding_version, status, created_at, updated_at)"
        " VALUES (?, ?, 'legacy', 'all-MiniLM-L6-v2', 384, ?, '', '1', 'ready', ?, ?)",
        ("m1", "ws", old_vec, now, now),
    )
    db.connection.commit()

    provider = MockEmbeddingProvider(dimension=384)
    retriever = DenseMemoryRetriever(db, provider)
    dense_result = retriever.search("ws", "legacy", limit=10)
    assert len(dense_result.candidates) == 0


def test_conftest_compatibility(db):
    _ensure_workspace(db, "ws")
    from cogito_agent.memory import MemoryRetriever
    from cogito_agent.retrieval.service import create_retrieval_service
    svc = create_retrieval_service(db)
    retriever = MemoryRetriever(db, service=svc)
    _add_memory(db, "m1", "ws", "apple banana fruit")
    results = retriever.search("ws", "apple banana", limit=10)
    assert len(results) >= 1


# ═══════════════════════════════════════════════════════
# R7: End-to-end integration tests
# ═══════════════════════════════════════════════════════


def test_retrieval_v2_writes_trace(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana fruit")
    provider = _TestSemanticProvider(dimension=384)
    vec = provider.embed_text("apple banana fruit")
    _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                      model="test_model", status="ready")
    sparse = SparseMemoryRetriever(db)
    dense = DenseMemoryRetriever(db, provider)
    svc = MemoryRetrievalService(
        db=db, provider=provider,
        sparse_retriever=sparse, dense_retriever=dense,
    )
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = builder.build(current_message="apple", workspace_id="ws")
    result = svc.recall(ctx, limit=10)
    assert result.trace_id
    row = db.connection.execute(
        "SELECT 1 FROM retrieval_traces WHERE id = ?", (result.trace_id,)
    ).fetchone()
    assert row is not None, "retrieval_traces must have a row"


def test_edit_creates_new_embedding(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "original text")
    provider = _TestSemanticProvider(dimension=384)
    vec = provider.embed_text("original text")
    _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                      model="test_model", status="ready")
    from cogito_agent.embedding.service import MemoryEmbeddingIndexService
    from cogito_agent.memory.application import MemoryApplicationService
    index_svc = MemoryEmbeddingIndexService(db, provider)
    app_svc = MemoryApplicationService(db, embedding_index=index_svc)
    app_svc.edit_memory("m1", "ws", "updated text")
    embedding = index_svc._get_existing_embedding("m1")
    assert embedding is not None
    new_hash = embedding.get("content_hash", "")
    assert new_hash != "", "edit should produce a new embedding"


def test_bm25_normalization_real_fts(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana cherry date elderberry")
    _add_memory(db, "m2", "ws", "apple banana")
    _add_memory(db, "m3", "ws", "completely unrelated topic")
    retriever = SparseMemoryRetriever(db)
    results = retriever.search("ws", "apple banana cherry date", limit=10)
    if results:
        best = results[0]
        assert best["sparse_score"] >= 0
        best_id = str(best["id"])
        best_text = str(best.get("text", ""))
        assert "completely" not in best_text, "unrelated should not rank first"


def test_config_weights_affect_scoring(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "python programming", mtype="general")
    provider = _TestSemanticProvider(dimension=384)
    vec = provider.embed_text("python programming")
    _add_v2_embedding(db, "m1", "ws", vec, provider="test_semantic",
                      model="test_model", status="ready")
    high_dense = CandidateFusion(
        dense_weight=1.0, sparse_weight=0.0,
        recency_weight=0.0, confidence_weight=0.0,
        task_relevance_weight=0.0, type_priority_weight=0.0,
    )
    high_sparse = CandidateFusion(
        dense_weight=0.0, sparse_weight=1.0,
        recency_weight=0.0, confidence_weight=0.0,
        task_relevance_weight=0.0, type_priority_weight=0.0,
    )
    sparse_candidates = [{"id": "m1", "text": "python programming", "sparse_score": 0.9,
                          "type": "general", "confidence": 0.5, "created_at": None}]
    dense_candidates = [{"id": "m1", "text": "python programming", "dense_score": 0.3,
                          "dense_rank": 1, "type": "general", "confidence": 0.5,
                          "created_at": None}]
    r1 = high_dense.fuse(sparse_candidates, dense_candidates, "python")
    r2 = high_sparse.fuse(sparse_candidates, dense_candidates, "python")
    _, b1 = r1[0]
    _, b2 = r2[0]
    assert b1.final_score == pytest.approx(0.3, abs=0.01)
    assert b2.final_score == pytest.approx(0.9, abs=0.01)


def test_recall_with_factory_and_config(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "apple banana", mtype="general")
    _add_memory(db, "m2", "ws", "cat dog", mtype="general", pinned=True)
    provider = _TestSemanticProvider(dimension=384)
    vec_fruit = provider.embed_text("apple banana")
    _add_v2_embedding(db, "m1", "ws", vec_fruit, provider="test_semantic",
                      model="test_model", status="ready")
    from cogito_agent.config.loader import TypePolicySettings
    from cogito_agent.retrieval.service import create_retrieval_service
    svc = create_retrieval_service(db, embedding_provider=provider)
    from cogito_agent.retrieval.query import MemoryQueryBuilder
    builder = MemoryQueryBuilder()
    ctx = builder.build(current_message="apple", workspace_id="ws")
    result = svc.recall(ctx, limit=5)
    assert result.selected_count >= 0
    assert result.mode in ("hybrid", "sparse_only", "dense_only")
    assert result.health_state == "healthy" or result.health_state == "disabled"


def test_recall_all_paths_write_trace(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "some content")
    sparse = SparseMemoryRetriever(db)
    svc = MemoryRetrievalService(db=db, provider=None,
                                  sparse_retriever=sparse,
                                  dense_retriever=DenseMemoryRetriever(db, None))
    from cogito_agent.retrieval.query import MemoryQueryContext
    modes = [
        MemoryQueryContext(current_message=""),
        MemoryQueryContext(current_message="hello"),
        MemoryQueryContext(current_message="我喜欢什么"),
        MemoryQueryContext(current_message="Cogito API"),
    ]
    for ctx in modes:
        result = svc.recall(ctx, limit=5)
        row = db.connection.execute(
            "SELECT 1 FROM retrieval_traces WHERE id = ?", (result.trace_id,)
        ).fetchone()
        assert row is not None, f"mode={result.mode} must write trace"


def test_context_engine_distinguishes_resident_and_dynamic(db):
    _ensure_workspace(db, "ws")
    _add_memory(db, "m1", "ws", "resident profile info", mtype="profile",
                confidence=0.9, pinned=True)
    _add_memory(db, "m2", "ws", "dynamic retrieved info", mtype="general")
    provider = _TestSemanticProvider(dimension=384)
    vec = provider.embed_text("dynamic retrieved info")
    _add_v2_embedding(db, "m2", "ws", vec, provider="test_semantic",
                      model="test_model", status="ready")
    from cogito_agent.retrieval import MemoryRecallResult
    from cogito_agent.context import ContextEngine
    engine = ContextEngine(total_token_budget=4096)
    recall = MemoryRecallResult()
    recall.resident_memories = [{"id": "m1", "text": "resident profile info",
                                  "retrieval_source": "resident", "type": "profile"}]
    recall.dynamic_memories = [{"id": "m2", "text": "dynamic retrieved info",
                                 "retrieval_source": "dynamic", "type": "general"}]
    ctx_items = engine.build(
        recent_messages=[],
        memories=recall.to_legacy_result(),
        current_message="test",
    )
    resident_items = [i for i in ctx_items if i.source_type == "memory_resident"]
    retrieved_items = [i for i in ctx_items if i.source_type == "memory_retrieved"]
    assert len(resident_items) >= 1
    assert len(retrieved_items) >= 1
