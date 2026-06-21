from __future__ import annotations

import uuid

import pytest

from cogito_agent.runtime import DriftMaintenance
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    WorkspaceRepository,
)


@pytest.fixture
def db() -> Database:
    d = Database(":memory:")
    d.initialize()
    return d


def _populate(db: Database) -> str:
    wid = str(uuid.uuid4())[:8]
    ws = WorkspaceRepository(db)
    ws.create(wid, "test")
    return wid


def test_consolidate_memories_dedup(db: Database) -> None:
    wid = _populate(db)
    mem = MemoryRepository(db)
    mid1 = str(uuid.uuid4())[:8]
    mid2 = str(uuid.uuid4())[:8]
    mem.create(mid1, wid, "duplicate text", "general")
    mem.create(mid2, wid, "duplicate text", "general")
    maint = DriftMaintenance(db)
    removed = maint.consolidate_memories(wid)
    assert removed >= 1
    remaining = mem.list_by_workspace(wid)
    assert len(remaining) == 1


def test_archive_stale_memories(db: Database) -> None:
    wid = _populate(db)
    mem = MemoryRepository(db)
    mid = str(uuid.uuid4())[:8]
    mem.create(mid, wid, "old memory", "general")
    db.connection.execute(
        "UPDATE memories SET created_at = datetime('now', '-60 days') WHERE id = ?",
        (mid,),
    )
    db.connection.commit()
    maint = DriftMaintenance(db)
    archived = maint.archive_stale_memories(days=30)
    assert archived >= 1
    cur = db.connection.execute("SELECT status FROM memories WHERE id = ?", (mid,))
    row = cur.fetchone()
    assert row is not None


def test_refresh_fts(db: Database) -> None:
    wid = _populate(db)
    mem = MemoryRepository(db)
    mem.create("fts-1", wid, "hello world", "general")
    maint = DriftMaintenance(db)
    count = maint.refresh_fts()
    assert isinstance(count, int)


def test_cleanup_traces(db: Database) -> None:
    wid = _populate(db)
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
        " VALUES ('old-trace', ?, 'evt', 'completed', datetime('now', '-100 days'))",
        (wid,),
    )
    db.connection.execute(
        "INSERT INTO traces (id, workspace_id, root_event_id, status, started_at)"
        " VALUES ('new-trace', ?, 'evt', 'completed', datetime('now', '-1 days'))",
        (wid,),
    )
    db.connection.commit()
    maint = DriftMaintenance(db)
    result = maint.cleanup_traces(days=90)
    assert result["traces"] >= 1
    cur = db.connection.execute("SELECT id FROM traces")
    remaining = [r["id"] for r in cur.fetchall()]
    assert "old-trace" not in remaining
    assert "new-trace" in remaining


def test_usage_report(db: Database) -> None:
    wid = _populate(db)
    sess = SessionRepository(db)
    sid = str(uuid.uuid4())[:8]
    sess.create(sid, wid, "test")
    msg = MessageRepository(db)
    msg.create("msg-u1", wid, sid, "user", "hi")
    msg.create("msg-u2", wid, sid, "assistant", "hello")
    maint = DriftMaintenance(db)
    report = maint.usage_report(wid)
    assert report["messages"] >= 2
    assert report["workspace_id"] == wid
