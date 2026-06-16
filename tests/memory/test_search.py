from __future__ import annotations

from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def test_search_fts_fallback(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-s", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-s1", "ws-s", "User likes Python programming")
    mem_repo.create("mem-s2", "ws-s", "Go is a compiled language")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-s", "Python")
    assert any("Python" in str(m.get("text", "")) for m in results)


def test_search_empty_query(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-empty", "test")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-empty", "")
    assert results == []


def test_search_across_workspaces_isolated(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-a", "A")
    ws_repo.create("ws-b", "B")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-a1", "ws-a", "Alice likes Python")
    mem_repo.create("mem-b1", "ws-b", "Bob likes Python")
    retriever = MemoryRetriever(db)
    results_a = retriever.search("ws-a", "Python")
    results_b = retriever.search("ws-b", "Python")
    assert all("ws-a" in str(m.get("workspace_id", "")) for m in results_a)
    assert all("ws-b" in str(m.get("workspace_id", "")) for m in results_b)


def test_search_respects_limit(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-limit", "test")
    mem_repo = MemoryRepository(db)
    for i in range(5):
        mem_repo.create(f"mem-l{i}", "ws-limit", f"Fact number {i} about Python")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-limit", "Python", limit=3)
    assert len(results) <= 3


def test_search_hybrid_fallback(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-hybrid", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-h1", "ws-hybrid", "Hybrid search test")
    retriever = MemoryRetriever(db)
    results = retriever.search_hybrid("ws-hybrid", "search")
    assert len(results) >= 1


def test_search_deleted_memories_excluded(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-del", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-d1", "ws-del", "Will be deleted")
    mem_repo.create("mem-d2", "ws-del", "Will remain")
    mem_repo.soft_delete("mem-d1", "ws-del")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-del", "deleted")
    assert not any(m.get("id") == "mem-d1" for m in results)
