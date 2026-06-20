from __future__ import annotations

import uuid

from cogito_agent.context import CompressionPolicy, SessionCompressionService
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository


def _database() -> tuple[Database, str, str]:
    db = Database()
    db.initialize()
    db.migrate()
    workspace_id = "workspace"
    session_id = "session"
    WorkspaceRepository(db).create(workspace_id, "Workspace")
    SessionRepository(db).create(session_id, workspace_id, "Session")
    return db, workspace_id, session_id


def _message(db: Database, workspace_id: str, session_id: str, content: str) -> str:
    message_id = str(uuid.uuid4())
    db.connection.execute(
        "INSERT INTO messages (id, workspace_id, session_id, role, content)"
        " VALUES (?, ?, ?, 'user', ?)",
        (message_id, workspace_id, session_id, content),
    )
    db.connection.commit()
    return message_id


def test_compression_creates_derived_record_without_mutating_messages() -> None:
    db, workspace_id, session_id = _database()
    for index in range(3):
        _message(db, workspace_id, session_id, f"message {index}")
    before = db.connection.execute("SELECT * FROM messages ORDER BY rowid").fetchall()
    service = SessionCompressionService(
        db, policy=CompressionPolicy(min_new_messages=2, min_new_characters=9999)
    )

    summary = service.update_summary(workspace_id, session_id)

    after = db.connection.execute("SELECT * FROM messages ORDER BY rowid").fetchall()
    assert summary is not None
    assert summary["derived"] == 1
    assert summary["source_message_count"] == 3
    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    db.close()


def test_compression_is_incremental_and_links_parent_summary() -> None:
    db, workspace_id, session_id = _database()
    _message(db, workspace_id, session_id, "first")
    service = SessionCompressionService(db)
    first = service.update_summary(workspace_id, session_id, force=True)
    assert first is not None
    last_message = _message(db, workspace_id, session_id, "second")

    second = service.update_summary(workspace_id, session_id, force=True)

    assert second is not None
    assert second["parent_summary_id"] == first["id"]
    assert second["source_message_count"] == 1
    assert second["through_message_id"] == last_message
    assert "first" in str(second["summary"])
    assert "second" in str(second["summary"])
    db.close()


def test_compression_policy_can_defer_small_updates() -> None:
    db, workspace_id, session_id = _database()
    _message(db, workspace_id, session_id, "short")
    service = SessionCompressionService(
        db, policy=CompressionPolicy(min_new_messages=5, min_new_characters=1000)
    )

    assert service.update_summary(workspace_id, session_id) is None
    assert service.get_latest(workspace_id, session_id) is None
    db.close()
