from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def test_search_memory(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-1", "ws-1", "User likes Python programming", "preference")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "Python")
    assert len(results) >= 1
    assert "Python" in str(results[0].get("text", ""))


def test_search_no_results(db: Database) -> None:
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "nonexistent")
    assert results == []


def test_list_recent(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-1", "ws-1", "fact 1")
    mem_repo.create("mem-2", "ws-1", "fact 2")
    retriever = MemoryRetriever(db)
    results = retriever.list_recent("ws-1")
    assert len(results) >= 2
