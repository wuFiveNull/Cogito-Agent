from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryEditRepository,
    MemoryRepository,
    WorkspaceRepository,
)


def _setup(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-1", "ws-1", "original text", "general")


def test_update_text_creates_version(db: Database) -> None:
    _setup(db)
    repo = MemoryEditRepository(db)
    repo.update_text("mem-1", "ws-1", "updated text")
    cur = db.connection.execute(
        "SELECT text, status FROM memories WHERE id != 'mem-1'"
        " AND workspace_id = 'ws-1' ORDER BY created_at DESC"
    )
    rows = cur.fetchall()
    stale_versions = [r for r in rows if r["status"] == "stale"]
    assert len(stale_versions) >= 1
    assert stale_versions[0]["text"] == "original text"


def test_update_text_nonexistent(db: Database) -> None:
    _setup(db)
    repo = MemoryEditRepository(db)
    result = repo.update_text("nonexistent", "ws-1", "text")
    assert result is None


def test_update_text_same_content_no_version(db: Database) -> None:
    _setup(db)
    repo = MemoryEditRepository(db)
    repo.update_text("mem-1", "ws-1", "original text")
    cur = db.connection.execute("SELECT COUNT(*) as cnt FROM memories WHERE status = 'stale'")
    assert cur.fetchone()["cnt"] == 0
