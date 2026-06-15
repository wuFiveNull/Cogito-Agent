from __future__ import annotations

import math
import struct

import pytest

from cogito_agent.memory.vector import (
    HybridRetriever,
    _cosine_similarity,
    _pack_embedding,
    _unpack_embedding,
)
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MemoryRepository, WorkspaceRepository


class _FakeEmbeddingService:
    model_name = "test-model"

    def encode(self, text: str) -> list[float]:
        dim = 4
        h = hash(text) % 10000
        return [math.sin(h + i) for i in range(dim)]

    def compute_similarity(
        self, a: list[float], b: list[float]
    ) -> float:
        return _cosine_similarity(a, b)


def test_cosine_similarity_identical() -> None:
    v = [1.0, 0.0, 0.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal() -> None:
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vec() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_pack_unpack_roundtrip() -> None:
    original = [0.1, 0.2, 0.3, -0.4]
    packed = _pack_embedding(original)
    assert isinstance(packed, bytes)
    assert len(packed) == 4 * 4
    restored = _unpack_embedding(packed)
    assert restored == pytest.approx(original)


def test_pack_embedding() -> None:
    vec = [1.0, 2.0, 3.0]
    packed = _pack_embedding(vec)
    expected = struct.pack("3f", 1.0, 2.0, 3.0)
    assert packed == expected


def test_hybrid_retriever_no_embeddings_falls_back(tmp_path) -> None:
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-test", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-1", "ws-test", "hello world")
    mem_repo.create("mem-2", "ws-test", "goodbye world")

    hybrid = HybridRetriever(db, _FakeEmbeddingService())
    results = hybrid.search("ws-test", "hello", limit=10)
    assert len(results) >= 1
    texts = {str(r["text"]) for r in results}
    assert "hello world" in texts


def test_hybrid_retriever_with_embeddings(tmp_path) -> None:
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-emb", "test")
    mem_repo = MemoryRepository(db)

    mem_repo.create("mem-a", "ws-emb", "apple banana")
    mem_repo.create("mem-b", "ws-emb", "cat dog")

    fake = _FakeEmbeddingService()
    for mid, text in [("mem-a", "apple banana"), ("mem-b", "cat dog")]:
        vec = fake.encode(text)
        blob = _pack_embedding(vec)
        db.connection.execute(
            "INSERT INTO memory_embeddings (memory_id, embedding, model_name)"
            " VALUES (?, ?, ?)",
            (mid, blob, fake.model_name),
        )
    db.connection.commit()

    hybrid = HybridRetriever(db, fake)
    results = hybrid.search("ws-emb", "apple", limit=10)
    assert len(results) >= 1
    assert any("apple" in str(r["text"]) for r in results)


def test_hybrid_retriever_empty_workspace(tmp_path) -> None:
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-empty", "test")

    hybrid = HybridRetriever(db, _FakeEmbeddingService())
    results = hybrid.search("ws-empty", "anything", limit=10)
    assert results == []


def test_search_hybrid_on_retriever(tmp_path) -> None:
    from cogito_agent.memory import MemoryRetriever

    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-hy", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-x", "ws-hy", "python programming")
    mem_repo.create("mem-y", "ws-hy", "java programming")

    retriever = MemoryRetriever(db)
    results = retriever.search_hybrid("ws-hy", "python", limit=10)
    assert len(results) >= 1
    assert any("python" in str(r["text"]) for r in results)


def test_search_hybrid_fallback_on_error(tmp_path) -> None:
    from cogito_agent.memory import MemoryRetriever

    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-fb", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-fb1", "ws-fb", "fallback test")
    mem_repo.create("mem-fb2", "ws-fb", "other data")

    retriever = MemoryRetriever(db)
    results = retriever.search_hybrid("ws-fb", "fallback", limit=10)
    assert len(results) >= 1
    assert any("fallback" in str(r["text"]) for r in results)
