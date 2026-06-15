from __future__ import annotations

import uuid

import pytest

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryEditRepository,
    MemoryRepository,
    WorkspaceRepository,
)


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


@pytest.fixture
def wid(db: Database) -> str:
    ws_id = "ws-mem-edit"
    WorkspaceRepository(db).create(ws_id, "test")
    return ws_id


def test_update_memory_text(db: Database, wid: str) -> None:
    mem_repo = MemoryRepository(db)
    mid = str(uuid.uuid4())
    mem_repo.create(mid, wid, "original text")
    edit_repo = MemoryEditRepository(db)
    result = edit_repo.update_text(mid, wid, "updated text")
    assert result is not None
    assert result["text"] == "updated text"


def test_update_nonexistent_memory(db: Database, wid: str) -> None:
    edit_repo = MemoryEditRepository(db)
    result = edit_repo.update_text("nonexistent", wid, "new text")
    assert result is None


def test_hard_delete_memory(db: Database, wid: str) -> None:
    mem_repo = MemoryRepository(db)
    mid = str(uuid.uuid4())
    mem_repo.create(mid, wid, "delete me")
    edit_repo = MemoryEditRepository(db)
    assert edit_repo.hard_delete(mid, wid) is True
    result = mem_repo.get_by_id(mid, wid)
    assert result is None


def test_list_by_type(db: Database, wid: str) -> None:
    mem_repo = MemoryRepository(db)
    mem_repo.create(str(uuid.uuid4()), wid, "profile info", type="profile")
    mem_repo.create(str(uuid.uuid4()), wid, "project info", type="project")
    edit_repo = MemoryEditRepository(db)
    profiles = edit_repo.list_by_type(wid, "profile")
    assert len(profiles) == 1
    assert profiles[0]["type"] == "profile"
