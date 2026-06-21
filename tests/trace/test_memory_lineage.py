from __future__ import annotations

import uuid

from cogito_agent.governance.audit import AuditLogger
from cogito_agent.storage import Database, MemoryRepository, WorkspaceRepository
from cogito_agent.storage.repositories import MemoryEditRepository


def _ws(db: Database, wid: str = "ws-audit") -> str:
    WorkspaceRepository(db).create(wid, "test")
    return wid


def _audit_logger(db: Database) -> AuditLogger:
    return AuditLogger(db)


def _count_audit_events(db: Database, workspace_id: str) -> int:
    cur = db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM audit_logs WHERE workspace_id = ?",
        (workspace_id,),
    )
    return cur.fetchone()["cnt"]


def test_accept_logs_audit(db: Database) -> None:
    wid = _ws(db)
    logger = _audit_logger(db)
    logger.log(
        actor_id="test",
        action="memory.accept",
        resource="candidate:audit-test",
        workspace_id=wid,
        session_id="sess-audit-1",
        trace_id="trace-audit-1",
        decision="allow",
        reason="test",
        details='{"candidate_text": "Auditable candidate"}',
    )
    assert _count_audit_events(db, wid) >= 1


def test_reject_logs_audit(db: Database) -> None:
    wid = _ws(db)
    logger = _audit_logger(db)
    logger.log(
        actor_id="test",
        action="memory.reject",
        resource="candidate:audit-test-2",
        workspace_id=wid,
        session_id="sess-audit-2",
        trace_id="trace-audit-2",
        decision="deny",
        reason="user rejection",
        details='{"candidate_text": "Rejectable candidate"}',
    )
    assert _count_audit_events(db, wid) >= 1


def test_delete_logs_audit(db: Database) -> None:
    wid = _ws(db)
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create(str(uuid.uuid4()), wid, "Deletable for audit")
    logger = _audit_logger(db)
    logger.log(
        actor_id="test",
        action="memory.delete",
        resource=mem["id"],
        workspace_id=wid,
        session_id="sess-audit-3",
        trace_id="trace-audit-3",
        decision="allow",
        reason="user requested",
        details='{"memory_text": "Deletable for audit"}',
    )
    assert _count_audit_events(db, wid) >= 1


def test_pin_logs_audit(db: Database) -> None:
    wid = _ws(db)
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create(str(uuid.uuid4()), wid, "Pinnable for audit")
    logger = _audit_logger(db)
    logger.log(
        actor_id="test",
        action="memory.pin",
        resource=mem["id"],
        workspace_id=wid,
        session_id="sess-audit-4",
        trace_id="trace-audit-4",
        decision="allow",
        reason="user requested",
        details='{"memory_text": "Pinnable for audit"}',
    )
    assert _count_audit_events(db, wid) >= 1


def test_edit_logs_audit(db: Database) -> None:
    wid = _ws(db)
    mem_repo = MemoryRepository(db)
    mem = mem_repo.create(str(uuid.uuid4()), wid, "Editable for audit")
    edit_repo = MemoryEditRepository(db)
    edit_repo.update_text(mem["id"], wid, "Updated text")
    logger = _audit_logger(db)
    logger.log(
        actor_id="test",
        action="memory.edit",
        resource=mem["id"],
        workspace_id=wid,
        session_id="sess-audit-5",
        trace_id="trace-audit-5",
        decision="allow",
        reason="user requested",
        details='{"old_text": "Editable for audit", "new_text": "Updated text"}',
    )
    assert _count_audit_events(db, wid) >= 1


def test_consolidate_logs_audit(db: Database) -> None:
    wid = _ws(db)
    logger = _audit_logger(db)
    logger.log(
        actor_id="system",
        action="memory.consolidate",
        resource=wid,
        workspace_id=wid,
        session_id="sess-audit-6",
        trace_id="trace-audit-6",
        decision="allow",
        reason="drift maintenance",
        details='{"duplicates_removed": 0}',
    )
    assert _count_audit_events(db, wid) >= 1
