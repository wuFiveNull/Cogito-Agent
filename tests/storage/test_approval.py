from __future__ import annotations

import pytest

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository, WorkspaceRepository


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


@pytest.fixture
def wid(db: Database) -> str:
    ws_id = "ws-approval"
    WorkspaceRepository(db).create(ws_id, "test")
    return ws_id


def test_create_approval(db: Database, wid: str) -> None:
    repo = ApprovalRepository(db)
    rec = repo.create(wid, "user", "read_file", "read", "file.txt", "test")
    assert rec["status"] == "pending"
    assert rec["capability_name"] == "read_file"


def test_resolve_approval(db: Database, wid: str) -> None:
    repo = ApprovalRepository(db)
    rec = repo.create(wid, "user", "write_file", "write", "file.txt", "need ok")
    resolved = repo.resolve(rec["id"], "allow", "admin")
    assert resolved is not None
    assert resolved["status"] == "allow"


def test_resolve_already_resolved(db: Database, wid: str) -> None:
    repo = ApprovalRepository(db)
    rec = repo.create(wid, "user", "delete", "delete", "file.txt", "")
    repo.resolve(rec["id"], "deny", "admin")
    second = repo.resolve(rec["id"], "allow", "admin")
    assert second is None


def test_list_pending(db: Database, wid: str) -> None:
    repo = ApprovalRepository(db)
    repo.create(wid, "user", "read", "read", "", "")
    pend = repo.list_pending(wid)
    assert len(pend) == 1


def test_list_pending_workspace_isolation(db: Database, wid: str) -> None:
    repo = ApprovalRepository(db)
    repo.create(wid, "user", "read", "read", "", "")
    repo.create("other-ws", "user", "write", "write", "", "")
    pend = repo.list_pending(wid)
    assert len(pend) == 1
