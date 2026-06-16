from __future__ import annotations

from cogito_agent.memory import MemoryRetriever
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository


def test_search_with_lineage_returns_source_lineage(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lg-1", "test")
    mem_repo = MemoryRepository(db)
    src = mem_repo.create("src-lg-1", "ws-lg-1", "Original source text", "profile")
    child = mem_repo.create("child-lg-1", "ws-lg-1", "Derived memory content", "general")
    db.connection.execute(
        "UPDATE memories SET source_id = ? WHERE id = ?",
        (src["id"], child["id"]),
    )
    db.connection.commit()

    retriever = MemoryRetriever(db)
    results = retriever.search_with_lineage("ws-lg-1", "Derived")
    assert len(results) >= 1
    r = next(m for m in results if m["id"] == child["id"])
    assert r["source_lineage"] is not None
    assert r["source_lineage"]["id"] == src["id"]
    assert r["source_lineage"]["text"] == "Original source text"
    assert r["source_lineage"]["type"] == "profile"


def test_search_with_lineage_no_source(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lg-2", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-no-src", "ws-lg-2", "Standalone memory item", "general")

    retriever = MemoryRetriever(db)
    results = retriever.search_with_lineage("ws-lg-2", "Standalone")
    assert len(results) >= 1
    r = next(m for m in results if m["id"] == "mem-no-src")
    assert r["source_lineage"] is None


def test_search_with_lineage_respects_include_archived(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lg-arch", "test")
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create("mem-lg-arch", "ws-lg-arch", "Archived lineage test entry", "general")
    mem_repo.archive(mem["id"], "ws-lg-arch")

    retriever = MemoryRetriever(db)
    results_default = retriever.search_with_lineage("ws-lg-arch", "Archived")
    assert not any(m["id"] == mem["id"] for m in results_default)

    results_incl = retriever.search_with_lineage("ws-lg-arch", "Archived", include_archived=True)
    assert any(m["id"] == mem["id"] for m in results_incl)


def test_search_with_lineage_excludes_deleted(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lg-del", "test")
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create("mem-lg-del", "ws-lg-del", "Deleted lineage entry", "general")
    mem_repo.soft_delete(mem["id"], "ws-lg-del")

    retriever = MemoryRetriever(db)
    results = retriever.search_with_lineage("ws-lg-del", "lineage")
    assert not any(m["id"] == mem["id"] for m in results)


def test_search_with_lineage_workspace_isolation(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-lg-a", "A")
    ws_repo.create("ws-lg-b", "B")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-lg-a1", "ws-lg-a", "Workspace A lineage content", "general")
    mem_repo.create("mem-lg-b1", "ws-lg-b", "Workspace B lineage content", "general")

    retriever = MemoryRetriever(db)
    results_a = retriever.search_with_lineage("ws-lg-a", "content")
    results_b = retriever.search_with_lineage("ws-lg-b", "content")
    assert all(m["workspace_id"] == "ws-lg-a" for m in results_a)
    assert all(m["workspace_id"] == "ws-lg-b" for m in results_b)


def test_search_include_archived_returns_archived(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-arch-s", "test")
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create("mem-arch-s1", "ws-arch-s", "Archived search test data", "general")
    mem_repo.archive(mem["id"], "ws-arch-s")

    retriever = MemoryRetriever(db)
    results = retriever.search("ws-arch-s", "Archived", include_archived=True)
    assert any(m["id"] == mem["id"] for m in results)


def test_search_default_excludes_archived(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-arch-s2", "test")
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create("mem-arch-s2", "ws-arch-s2", "Another archived item here", "general")
    mem_repo.archive(mem["id"], "ws-arch-s2")

    retriever = MemoryRetriever(db)
    results = retriever.search("ws-arch-s2", "archived")
    assert not any(m["id"] == mem["id"] for m in results)
