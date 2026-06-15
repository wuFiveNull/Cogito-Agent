from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def test_create_memory(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    repo = MemoryRepository(db)
    mem = repo.create("mem-1", "ws-1", "User likes Python", "profile")
    assert mem["text"] == "User likes Python"
    assert mem["type"] == "profile"


def test_memory_workspace_isolation(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "a")
    ws_repo.create("ws-2", "b")
    repo = MemoryRepository(db)
    repo.create("mem-1", "ws-1", "fact")
    assert repo.get_by_id("mem-1", "ws-2") is None


def test_soft_delete_memory(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    repo = MemoryRepository(db)
    repo.create("mem-1", "ws-1", "fact")
    repo.soft_delete("mem-1", "ws-1")
    assert repo.get_by_id("mem-1", "ws-1") is None
