from __future__ import annotations

from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def test_edit_archived_memory_succeeds(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-force-arch", "test")
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create("mem-fa1", "ws-force-arch", "Original archived content", "general")
    mem_repo.archive(mem["id"], "ws-force-arch")
    result = mem_repo.edit_text(mem["id"], "ws-force-arch", "Edited archived content")
    assert result is True
    updated = mem_repo.get_by_id(mem["id"], "ws-force-arch")
    assert updated is not None
    assert updated["text"] == "Edited archived content"


def test_edit_deleted_memory_fails(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-force-del", "test")
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create("mem-fd1", "ws-force-del", "About to be deleted", "general")
    mem_repo.soft_delete(mem["id"], "ws-force-del")
    result = mem_repo.edit_text(mem["id"], "ws-force-del", "Should not apply")
    assert result is False


def test_search_with_lineage_cross_workspace_isolation(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-f-a", "A")
    ws_repo.create("ws-f-b", "B")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-fa1", "ws-f-a", "Alice memory data point", "general")
    mem_repo.create("mem-fb1", "ws-f-b", "Bob memory data point", "general")

    retriever = MemoryRetriever(db)
    results_a = retriever.search_with_lineage("ws-f-a", "data")
    results_b = retriever.search_with_lineage("ws-f-b", "data")
    assert all(m["workspace_id"] == "ws-f-a" for m in results_a)
    assert all(m["workspace_id"] == "ws-f-b" for m in results_b)
