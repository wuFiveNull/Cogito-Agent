from __future__ import annotations

from cogito_agent.application import (
    ApprovalApplicationService,
    InboxApplicationService,
    RunApplicationService,
    SessionApplicationService,
    WorkspaceApplicationService,
)
from cogito_agent.autonomy import FeedbackStore, Outbox
from cogito_agent.governance import AuditLogger
from cogito_agent.runs import RunRepository
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository


def _db() -> Database:
    db = Database()
    db.initialize()
    db.migrate()
    return db


def test_workspace_and_session_mutations_are_audited() -> None:
    db = _db()
    workspace = WorkspaceApplicationService(db)
    workspace.create_workspace("Personal", workspace_id="personal")
    session_service = SessionApplicationService(db)
    session = session_service.create("personal")
    assert session_service.archive("personal", str(session["id"]))
    count = db.connection.execute(
        "SELECT COUNT(*) FROM audit_logs"
        " WHERE action IN ('workspace.create','session_created','session_archived')"
    ).fetchone()[0]
    assert count == 3
    db.close()


def test_approval_service_is_idempotent() -> None:
    db = _db()
    repository = ApprovalRepository(db)
    service = ApprovalApplicationService(repository, AuditLogger(db))
    approval = service.create(
        workspace_id="workspace",
        actor_id="user",
        capability_name="test",
    )
    approval_id = str(approval["id"])
    result, existing = service.resolve(
        approval_id,
        decision="approved",
        actor_id="console",
        workspace_id="workspace",
    )
    assert result is not None and existing is None
    result, existing = service.resolve(
        approval_id,
        decision="approved",
        actor_id="console",
        workspace_id="workspace",
    )
    assert result is None and existing is not None
    db.close()


def test_inbox_service_controls_delivery_state() -> None:
    db = _db()
    audit = AuditLogger(db)
    outbox = Outbox(db)
    service = InboxApplicationService(
        outbox,
        FeedbackStore(db, audit),
        audit,
    )
    item_id = outbox.enqueue("event", "decision", "title")
    assert service.mark_read(item_id)
    assert service.dismiss(item_id, workspace_id="*", actor_id="user")
    assert service.retry(item_id, workspace_id="*", actor_id="user")
    assert outbox.get_message(item_id)["status"] == "pending"  # type: ignore[index]
    db.close()


def test_run_retry_dispatches_the_original_run() -> None:
    db = _db()
    repository = RunRepository(db)
    run = repository.create(run_type="skill", workspace_id="workspace")
    run_id = str(run["id"])
    assert repository.finish(run_id, status="failed")
    dispatched: list[str] = []
    service = RunApplicationService(
        repository,
        AuditLogger(db),
        retry_dispatcher=lambda item: dispatched.append(str(item["id"])),
    )

    assert service.retry(run_id, workspace_id="workspace")
    assert dispatched == [run_id]
    assert repository.get(run_id)["status"] == "pending"  # type: ignore[index]
    db.close()
