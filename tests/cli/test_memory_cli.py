from __future__ import annotations

import uuid

from cogito_agent.memory import CandidateExtractor, MemoryRetriever
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryCandidateRepository,
    MemoryRepository,
)


def _make_workspace(db: Database) -> str:
    wid = "ws-mem-cli"
    db.connection.execute(
        "INSERT OR IGNORE INTO workspaces (id, name) VALUES (?, ?)", (wid, wid)
    )
    db.connection.commit()
    return wid


def _make_memory(db: Database, wid: str, text: str, mtype: str = "general") -> dict:
    repo = MemoryRepository(db)
    return repo.create(str(uuid.uuid4()), wid, text, type=mtype)


def _make_candidate(db: Database, wid: str, text: str) -> dict:
    repo = MemoryCandidateRepository(db)
    return repo.create(wid, text)


def test_memory_list_empty() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    repo = MemoryRepository(db)
    assert repo.list_by_workspace(wid) == []


def test_memory_list_with_data() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    _make_memory(db, wid, "User loves Python")
    _make_memory(db, wid, "Works at Acme Corp")
    repo = MemoryRepository(db)
    memories = repo.list_by_workspace(wid)
    assert len(memories) == 2


def test_memory_search() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    _make_memory(db, wid, "User loves Python programming")
    _make_memory(db, wid, "Prefers Go for backend")
    retriever = MemoryRetriever(db)
    results = retriever.search(wid, "Python")
    assert len(results) >= 1
    assert "Python" in str(results[0].get("text", ""))


def test_memory_search_no_results() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    retriever = MemoryRetriever(db)
    assert retriever.search(wid, "nonexistent") == []


def test_memory_review_empty() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    repo = MemoryCandidateRepository(db)
    assert repo.list_pending(wid) == []


def test_memory_review_with_candidates() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    _make_candidate(db, wid, "Candidate memory 1")
    _make_candidate(db, wid, "Candidate memory 2")
    repo = MemoryCandidateRepository(db)
    pending = repo.list_pending(wid)
    assert len(pending) == 2


def test_memory_accept_candidate() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    cand = _make_candidate(db, wid, "Acceptable memory")
    repo = MemoryCandidateRepository(db)
    accepted = repo.accept(cand["id"])
    assert accepted is not None
    assert accepted["status"] == "accepted"
    mem_repo = MemoryRepository(db)
    memories = mem_repo.list_by_workspace(wid)
    assert any("Acceptable memory" in str(m.get("text", "")) for m in memories)


def test_memory_accept_nonexistent() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    repo = MemoryCandidateRepository(db)
    assert repo.accept("nonexistent") is None


def test_memory_reject_candidate() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    cand = _make_candidate(db, wid, "Rejectable memory")
    repo = MemoryCandidateRepository(db)
    rejected = repo.reject(cand["id"])
    assert rejected is not None
    assert rejected["status"] == "rejected"


def test_memory_reject_nonexistent() -> None:
    db = Database(":memory:")
    db.initialize()
    repo = MemoryCandidateRepository(db)
    assert repo.reject("nonexistent") is None


def test_memory_delete() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    mem = _make_memory(db, wid, "Deletable memory")
    from cogito_agent.storage.repositories import MemoryEditRepository
    edit_repo = MemoryEditRepository(db)
    assert edit_repo.hard_delete(mem["id"], wid) is True
    assert edit_repo.hard_delete("nonexistent", wid) is False


def test_memory_pin() -> None:
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    wid = _make_workspace(db)
    mem = _make_memory(db, wid, "Pinnable memory")
    repo = MemoryRepository(db)
    assert repo.pin(mem["id"], wid) is True
    updated = db.connection.execute(
        "SELECT pinned_at FROM memories WHERE id = ?", (mem["id"],)
    ).fetchone()
    assert updated["pinned_at"] is not None


def test_memory_pin_nonexistent() -> None:
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    wid = _make_workspace(db)
    repo = MemoryRepository(db)
    assert repo.pin("nonexistent", wid) is False


def test_memory_archive() -> None:
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    wid = _make_workspace(db)
    mem = _make_memory(db, wid, "Archivable memory")
    repo = MemoryRepository(db)
    assert repo.archive(mem["id"], wid) is True
    updated = db.connection.execute(
        "SELECT archived_at FROM memories WHERE id = ?", (mem["id"],)
    ).fetchone()
    assert updated["archived_at"] is not None


def test_memory_archive_nonexistent() -> None:
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    wid = _make_workspace(db)
    repo = MemoryRepository(db)
    assert repo.archive("nonexistent", wid) is False


def test_memory_consolidate() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    repo = MemoryRepository(db)
    repo.create(str(uuid.uuid4()), wid, "Duplicate text")
    repo.create(str(uuid.uuid4()), wid, "Duplicate text")
    repo.create(str(uuid.uuid4()), wid, "Unique text")
    from cogito_agent.runtime.drift import DriftMaintenance
    dm = DriftMaintenance(db)
    removed = dm.consolidate_memories(wid)
    assert removed == 1
    memories = repo.list_by_workspace(wid)
    assert len(memories) == 2


def test_memory_consolidate_no_duplicates() -> None:
    db = Database(":memory:")
    db.initialize()
    wid = _make_workspace(db)
    repo = MemoryRepository(db)
    repo.create(str(uuid.uuid4()), wid, "Text A")
    repo.create(str(uuid.uuid4()), wid, "Text B")
    from cogito_agent.runtime.drift import DriftMaintenance
    dm = DriftMaintenance(db)
    assert dm.consolidate_memories(wid) == 0
