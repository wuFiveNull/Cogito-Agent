from __future__ import annotations

import uuid

from cogito_agent.runtime.drift import DriftMaintenance
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository
from cogito_agent.storage.repositories import (
    MemoryCandidateRepository,
    MemoryEditRepository,
)


def _ws(db: Database, wid: str = "ws-lifecycle") -> str:
    WorkspaceRepository(db).create(wid, "test")
    return wid


def test_accept_consolidate_archive_delete_flow(db: Database) -> None:
    wid = _ws(db)
    cand_repo = MemoryCandidateRepository(db)
    mem_repo = MemoryRepository(db)

    cand = cand_repo.create(wid, "Lifecycle memory text X", type="general")
    accepted = cand_repo.accept(cand["id"])
    assert accepted is not None
    assert accepted["status"] == "accepted"

    memories = mem_repo.list_by_workspace(wid)
    mem = next((m for m in memories if "Lifecycle memory text X" in str(m.get("text", ""))), None)
    assert mem is not None, "accepted candidate should appear as memory"

    mem_repo.create(str(uuid.uuid4()), wid, "Lifecycle memory text X")
    dm = DriftMaintenance(db)
    removed = dm.consolidate_memories(wid)
    assert removed == 1

    assert mem_repo.archive(mem["id"], wid) is True
    archived = db.connection.execute(
        "SELECT archived_at FROM memories WHERE id = ?", (mem["id"],)
    ).fetchone()
    assert archived is not None and archived["archived_at"] is not None

    edit_repo = MemoryEditRepository(db)
    assert edit_repo.hard_delete(mem["id"], wid) is True
    assert mem_repo.get_by_id(mem["id"], wid) is None


def test_pin_archive_independent(db: Database) -> None:
    wid = _ws(db)
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create(str(uuid.uuid4()), wid, "Pin-and-archive test")

    assert mem_repo.pin(mem["id"], wid) is True
    assert mem_repo.archive(mem["id"], wid) is True

    row = db.connection.execute(
        "SELECT pinned_at, archived_at FROM memories WHERE id = ?", (mem["id"],)
    ).fetchone()
    assert row is not None
    assert row["pinned_at"] is not None
    assert row["archived_at"] is not None


def test_soft_delete_excludes_from_list(db: Database) -> None:
    wid = _ws(db)
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create(str(uuid.uuid4()), wid, "Soft delete test")
    mem_repo.soft_delete(mem["id"], wid)
    assert mem_repo.get_by_id(mem["id"], wid) is None
    ids = [m["id"] for m in mem_repo.list_by_workspace(wid)]
    assert mem["id"] not in ids


def test_edit_preserves_lineage(db: Database) -> None:
    wid = _ws(db)
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create(str(uuid.uuid4()), wid, "Original text")
    edit_repo = MemoryEditRepository(db)
    updated = edit_repo.update_text(mem["id"], wid, "Edited text")
    assert updated is not None
    assert updated["text"] == "Edited text"

    stale = db.connection.execute(
        "SELECT * FROM memories WHERE source_id = ? AND status = 'stale'",
        (mem["id"],),
    ).fetchone()
    assert stale is not None
    assert stale["text"] == "Original text"
