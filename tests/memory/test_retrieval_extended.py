from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def _setup(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-1", "ws-1", "User likes Python", "preference")
    mem_repo.create("mem-2", "ws-1", "Project uses FastAPI", "project")
    mem_repo.create("mem-3", "ws-1", "Alice works at Acme", "profile")
    db.connection.execute(
        "UPDATE memories SET confidence = 0.9 WHERE id = 'mem-3'"
    )
    db.connection.commit()


def test_search_ranks_profile_higher(db: Database) -> None:
    _setup(db)
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "Python")
    assert len(results) >= 1
    assert results[0]["type"] == "preference"


def test_search_ranks_by_confidence(db: Database) -> None:
    _setup(db)
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "Alice")
    assert len(results) >= 1
    assert results[0]["id"] == "mem-3"
    assert results[0]["confidence"] == 0.9


def test_search_ranks_consolidated_higher(db: Database) -> None:
    _setup(db)
    db.connection.execute(
        "UPDATE memories SET status = 'consolidated' WHERE id = 'mem-1'"
    )
    db.connection.commit()
    retriever = MemoryRetriever(db)
    results = retriever.search("ws-1", "Python")
    assert len(results) >= 1
    assert results[0]["id"] == "mem-1"
