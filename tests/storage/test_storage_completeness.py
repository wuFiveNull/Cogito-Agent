from __future__ import annotations

import uuid

from cogito_agent.storage import Database, register_migration
from cogito_agent.storage.database import _SCHEMA_VERSION
from cogito_agent.storage.repositories import (
    FileArtifactRepository,
    MemoryRepository,
    MessageRepository,
    SessionRepository,
    WorkspaceRepository,
)


def ws(db: Database) -> tuple[str, str]:
    wid = str(uuid.uuid4())[:8]
    sid = str(uuid.uuid4())[:8]
    ws_repo = WorkspaceRepository(db)
    ws_repo.create(wid, "test")
    sess_repo = SessionRepository(db)
    sess_repo.create(sid, wid, "test-session")
    msg_repo = MessageRepository(db)
    msg_repo.create("msg-1", wid, sid, "user", "hello")
    msg_repo.create("msg-2", wid, sid, "assistant", "hi")
    mem_repo = MemoryRepository(db)
    mem_repo.create("mem-1", wid, "test memory", "general")
    fa_repo = FileArtifactRepository(db)
    fa_repo.create("fa-1", wid, "/tmp/test.txt", "text/plain")
    return wid, sid


# ─── L.1 Hard Delete ────────────────────────────────────────────────────


def test_hard_delete_workspace(db: Database) -> None:
    wid, sid = ws(db)
    ws_repo = WorkspaceRepository(db)
    assert ws_repo.get_by_id(wid) is not None
    assert ws_repo.hard_delete(wid) is True
    assert ws_repo.get_by_id(wid) is None


def test_hard_delete_workspace_cascades(db: Database) -> None:
    wid, sid = ws(db)
    ws_repo = WorkspaceRepository(db)
    ws_repo.hard_delete(wid)
    sess_repo = SessionRepository(db)
    assert sess_repo.get_by_id(sid, wid) is None
    msg_repo = MessageRepository(db)
    assert msg_repo.get_by_id("msg-1", wid) is None
    mem_repo = MemoryRepository(db)
    assert mem_repo.get_by_id("mem-1", wid) is None
    fa_repo = FileArtifactRepository(db)
    assert fa_repo.get_by_id("fa-1", wid) is None


def test_hard_delete_workspace_nonexistent(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    assert ws_repo.hard_delete("nonexistent") is False


def test_hard_delete_session(db: Database) -> None:
    wid, sid = ws(db)
    sess_repo = SessionRepository(db)
    assert sess_repo.get_by_id(sid, wid) is not None
    assert sess_repo.hard_delete(sid, wid) is True
    assert sess_repo.get_by_id(sid, wid) is None


def test_hard_delete_session_cascades_messages(db: Database) -> None:
    wid, sid = ws(db)
    sess_repo = SessionRepository(db)
    sess_repo.hard_delete(sid, wid)
    msg_repo = MessageRepository(db)
    assert msg_repo.get_by_id("msg-1", wid) is None
    assert msg_repo.get_by_id("msg-2", wid) is None


def test_hard_delete_session_nonexistent(db: Database) -> None:
    sess_repo = SessionRepository(db)
    assert sess_repo.hard_delete("nonexistent", "ws-1") is False


def test_hard_delete_file_artifact(db: Database) -> None:
    wid, _sid = ws(db)
    fa_repo = FileArtifactRepository(db)
    assert fa_repo.get_by_id("fa-1", wid) is not None
    assert fa_repo.hard_delete("fa-1", wid) is True
    assert fa_repo.get_by_id("fa-1", wid) is None


def test_hard_delete_file_artifact_nonexistent(db: Database) -> None:
    fa_repo = FileArtifactRepository(db)
    assert fa_repo.hard_delete("nonexistent", "ws-1") is False


def test_hard_delete_message_by_session(db: Database) -> None:
    wid, sid = ws(db)
    msg_repo = MessageRepository(db)
    assert msg_repo.hard_delete_by_session(sid, wid) >= 2
    assert msg_repo.get_by_id("msg-1", wid) is None


# ─── L.2 Full Data Export ────────────────────────────────────────────────


def test_export_workspace_basic(db: Database) -> None:
    wid, _sid = ws(db)
    data = db.export_workspace(wid)
    assert data["workspace_id"] == wid
    assert data.get("workspace") is not None
    assert len(data.get("sessions", [])) >= 1
    assert len(data.get("messages", [])) >= 2
    assert len(data.get("memories", [])) >= 1
    assert len(data.get("file_artifacts", [])) >= 1


def test_export_workspace_nonexistent(db: Database) -> None:
    data = db.export_workspace("nonexistent")
    assert data["workspace_id"] == "nonexistent"
    assert data.get("workspace") is None


# ─── L.3 Schema Migration ──────────────────────────────────────────────


def test_schema_version_init(db: Database) -> None:
    ver = db.current_version()
    assert ver == _SCHEMA_VERSION


def test_migrate_applies_registered(db: Database) -> None:
    register_migration(999, "CREATE TABLE IF NOT EXISTS _mig_test (x INTEGER);")
    applied = db.migrate()
    assert 999 in applied
    cur = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_mig_test'"
    )
    assert cur.fetchone() is not None
    ver = db.current_version()
    assert ver >= 999


def test_migrate_idempotent(db: Database) -> None:
    register_migration(998, "CREATE TABLE IF NOT EXISTS _mig_test2 (x INTEGER);")
    applied1 = db.migrate()
    applied2 = db.migrate()
    assert 998 in applied1
    assert 998 not in applied2
