from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MemoryRepository, WorkspaceRepository


def _setup_ws(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")


def test_fts_search(db: Database) -> None:
    _setup_ws(db)
    repo = MemoryRepository(db)
    repo.create("m1", "ws-1", "User loves Python programming")
    repo.create("m2", "ws-1", "User prefers JavaScript")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "Python")
    assert len(results) >= 1
    texts = [r["text"] for r in results]
    assert any("Python" in t for t in texts)


def test_fts_fallback_like(db: Database) -> None:
    _setup_ws(db)
    repo = MemoryRepository(db)
    repo.create("m1", "ws-1", "some special keyword here")
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "special")
    assert len(results) >= 1
