from __future__ import annotations

from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def test_list_recent_returns_correct_count(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lr-cnt", "test")
    mem_repo = MemoryRepository(db)
    for i in range(5):
        mem_repo.create(f"mem-lr-c{i}", "ws-lr-cnt", f"List memory {i}", "general")

    retriever = MemoryRetriever(db)
    results = retriever.list_recent("ws-lr-cnt")
    assert len(results) >= 5


def test_list_recent_excludes_deleted(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lr-del", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-lr-d1", "ws-lr-del", "Keep this one", "general")
    mem_repo.create("mem-lr-d2", "ws-lr-del", "Delete this one", "general")
    mem_repo.soft_delete("mem-lr-d2", "ws-lr-del")

    retriever = MemoryRetriever(db)
    results = retriever.list_recent("ws-lr-del")
    mids = [m["id"] for m in results]
    assert "mem-lr-d1" in mids
    assert "mem-lr-d2" not in mids


def test_list_recent_includes_archived(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lr-arch", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-lr-a1", "ws-lr-arch", "Archived entry", "general")
    mem_repo.archive("mem-lr-a1", "ws-lr-arch")
    mem_repo.create("mem-lr-a2", "ws-lr-arch", "Active entry", "general")

    retriever = MemoryRetriever(db)
    results = retriever.list_recent("ws-lr-arch")
    mids = [m["id"] for m in results]
    assert "mem-lr-a1" in mids
    assert "mem-lr-a2" in mids


def test_list_recent_includes_pinned(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lr-pin", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-lr-p1", "ws-lr-pin", "Pinned memory info", "general")
    mem_repo.pin("mem-lr-p1", "ws-lr-pin")
    mem_repo.create("mem-lr-p2", "ws-lr-pin", "Regular memory info", "general")

    retriever = MemoryRetriever(db)
    results = retriever.list_recent("ws-lr-pin")
    mids = [m["id"] for m in results]
    assert "mem-lr-p1" in mids
    assert "mem-lr-p2" in mids


def test_list_recent_ordering(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lr-ord", "test")
    mem_repo = MemoryRepository(db)
    old = mem_repo.create("mem-lr-old", "ws-lr-ord", "Older memory text", "general")
    new = mem_repo.create("mem-lr-new", "ws-lr-ord", "Newer memory text", "general")
    db.connection.execute(
        "UPDATE memories SET created_at = '2024-01-01T00:00:00' WHERE id = ?",
        (old["id"],),
    )
    db.connection.execute(
        "UPDATE memories SET created_at = '2025-01-01T00:00:00' WHERE id = ?",
        (new["id"],),
    )
    db.connection.commit()

    retriever = MemoryRetriever(db)
    results = retriever.list_recent("ws-lr-ord")
    assert len(results) >= 2
    assert results[0]["id"] == new["id"]
