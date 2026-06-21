from __future__ import annotations

import os
import tempfile

import pytest

from cogito_agent.memory.vector import (
    EmbeddingService,
    HybridRetriever,
    MockEmbeddingService,
    _cosine_similarity,
    _pack_embedding,
)
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


def _add_memory(
    db: Database,
    mid: str,
    ws: str,
    text: str,
    mtype: str = "general",
    confidence: float = 0.5,
    pinned: bool = False,
) -> None:
    import datetime

    now = datetime.datetime.utcnow().isoformat()
    pinned_at = now if pinned else None
    db.connection.execute(
        "INSERT INTO memories (id, workspace_id, text, type, confidence, pinned_at,"
        " status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
        (mid, ws, text, mtype, confidence, pinned_at, now, now),
    )
    db.connection.execute(
        "INSERT INTO memories_fts (rowid, text, summary) VALUES (?, ?, ?)",
        (
            db.connection.execute("SELECT rowid FROM memories WHERE id = ?", (mid,)).fetchone()[0],
            text,
            text[:100],
        ),
    )
    db.connection.commit()


def test_mock_embedding_service_no_deps() -> None:
    svc = MockEmbeddingService()
    vec = svc.encode("hello world")
    assert len(vec) == 384
    assert all(isinstance(v, float) for v in vec)
    # Deterministic
    vec2 = svc.encode("hello world")
    assert vec == vec2


def test_mock_embedding_different_texts() -> None:
    svc = MockEmbeddingService()
    a = svc.encode("apple banana")
    b = svc.encode("cat dog")
    # Different texts should have different vectors
    assert a != b


def test_mock_embedding_cosine_similarity() -> None:
    svc = MockEmbeddingService()
    a = svc.encode("hello world")
    b = svc.encode("hello world")
    sim = svc.compute_similarity(a, b)
    assert abs(sim - 1.0) < 0.001
    # Different texts should have lower similarity
    c = svc.encode("completely unrelated")
    sim_diff = svc.compute_similarity(a, c)
    assert sim_diff < 0.9


def test_mock_embedding_properties() -> None:
    svc = MockEmbeddingService(dimension=128)
    assert svc.dimension == 128
    assert svc.model_name == "mock"
    assert len(svc.encode("test")) == 128


def test_embedding_service_fallback_to_mock() -> None:
    svc = EmbeddingService()
    # Should work without sentence-transformers installed
    vec = svc.encode("test fallback")
    assert len(vec) == 384
    assert svc.model_name == "mock"


def test_embedding_service_compute_similarity() -> None:
    svc = EmbeddingService()
    a = svc.encode("hello")
    b = svc.encode("hello")
    assert abs(svc.compute_similarity(a, b) - 1.0) < 0.001


def test_hybrid_retriever_search_with_mock_embeddings(db: Database) -> None:
    ws_id = "ws-hybrid-test"
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "test"))
    _add_memory(db, "h1", ws_id, "apple banana fruit", confidence=0.9)
    _add_memory(db, "h2", ws_id, "cat dog animal", confidence=0.8)
    _add_memory(db, "h3", ws_id, "python programming code", confidence=0.7)

    # Create mock embeddings
    svc = MockEmbeddingService()
    for mid, text in [
        ("h1", "apple banana fruit"),
        ("h2", "cat dog animal"),
        ("h3", "python programming code"),
    ]:
        vec = svc.encode(text)
        db.connection.execute(
            "INSERT OR REPLACE INTO memory_embeddings_v2"
            " (memory_id, workspace_id, provider_name, model_name, dimension, embedding,"
            "  content_hash, embedding_version, status)"
            " VALUES (?, ?, ?, ?, ?, ?, '', '2', 'active')",
            (mid, ws_id, "mock", svc.model_name, svc.dimension, _pack_embedding(vec)),
        )
    db.connection.commit()

    hybrid = HybridRetriever(db, svc)
    results = hybrid.search(ws_id, "apple", limit=10)
    assert len(results) >= 1
    texts = [str(r["text"]) for r in results]
    assert any("apple" in t for t in texts)


def test_hybrid_retriever_fallback_no_embeddings(db: Database) -> None:
    ws_id = "ws-no-emb"
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "test"))
    _add_memory(db, "f1", ws_id, "abc def ghi")

    hybrid = HybridRetriever(db, MockEmbeddingService())
    results = hybrid.search(ws_id, "abc", limit=10)
    assert len(results) >= 1
    assert "abc" in str(results[0]["text"])


def test_hybrid_retriever_workspace_isolation(db: Database) -> None:
    ws_a = "ws-iso-a"
    ws_b = "ws-iso-b"
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_a, "a"))
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_b, "b"))
    _add_memory(db, "i1", ws_a, "secret data")

    svc = MockEmbeddingService()
    vec = svc.encode("secret data")
    db.connection.execute(
        "INSERT OR REPLACE INTO memory_embeddings_v2"
        " (memory_id, workspace_id, provider_name, model_name, dimension, embedding,"
        "  content_hash, embedding_version, status)"
        " VALUES (?, ?, ?, ?, ?, ?, '', '2', 'active')",
        ("i1", ws_a, "mock", svc.model_name, svc.dimension, _pack_embedding(vec)),
    )
    db.connection.commit()

    hybrid = HybridRetriever(db, svc)
    results_a = hybrid.search(ws_a, "secret", limit=10)
    assert len(results_a) >= 1
    results_b = hybrid.search(ws_b, "secret", limit=10)
    assert len(results_b) == 0


def test_hybrid_retriever_pinned_boost(db: Database) -> None:
    ws_id = "ws-pin"
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "test"))
    _add_memory(db, "p1", ws_id, "important data", confidence=0.5, pinned=True)
    _add_memory(db, "p2", ws_id, "other data", confidence=0.5)

    svc = MockEmbeddingService()
    for mid, text in [("p1", "important data"), ("p2", "other data")]:
        vec = svc.encode(text)
        db.connection.execute(
            "INSERT OR REPLACE INTO memory_embeddings_v2"
            " (memory_id, workspace_id, provider_name, model_name, dimension, embedding,"
            "  content_hash, embedding_version, status)"
            " VALUES (?, ?, ?, ?, ?, ?, '', '2', 'active')",
            (mid, ws_id, "mock", svc.model_name, svc.dimension, _pack_embedding(vec)),
        )
    db.connection.commit()

    hybrid = HybridRetriever(db, svc)
    results = hybrid.search(ws_id, "data", limit=10)
    assert len(results) >= 2
    # Pinned item should rank first
    assert results[0]["id"] == "p1"


def test_hybrid_retriever_archived_excluded(db: Database) -> None:
    ws_id = "ws-arch2"
    db.connection.execute("INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "test"))
    import datetime

    now = datetime.datetime.utcnow().isoformat()
    db.connection.execute(
        "INSERT INTO memories (id, workspace_id, text, type, status, created_at, updated_at)"
        " VALUES (?, ?, ?, 'general', 'active', ?, ?)",
        ("arch-mem", ws_id, "archived content", now, now),
    )
    db.connection.execute(
        "UPDATE memories SET archived_at = ? WHERE id = ?",
        (now, "arch-mem"),
    )
    db.connection.commit()

    svc = MockEmbeddingService()
    vec = svc.encode("archived content")
    db.connection.execute(
        "INSERT OR REPLACE INTO memory_embeddings_v2"
        " (memory_id, workspace_id, provider_name, model_name, dimension, embedding,"
        "  content_hash, embedding_version, status)"
        " VALUES (?, ?, ?, ?, ?, ?, '', '2', 'active')",
        ("arch-mem", ws_id, "mock", svc.model_name, svc.dimension, _pack_embedding(vec)),
    )
    db.connection.commit()

    hybrid = HybridRetriever(db, svc)
    results = hybrid.search(ws_id, "archived", limit=10)
    # Archived should be excluded by default
    assert len(results) == 0


def test_cosine_similarity_identical() -> None:
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(a, b) - 1.0) < 0.001


def test_cosine_similarity_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine_similarity(a, b)) < 0.001


def test_cosine_similarity_zero_vec() -> None:
    a = [1.0, 0.0]
    b = [0.0, 0.0]
    assert _cosine_similarity(a, b) == 0.0
