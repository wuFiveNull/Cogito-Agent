from __future__ import annotations

import uuid

import pytest

from cogito_agent.autonomy import (
    DecisionStore,
    FeedbackStore,
    NotificationGate,
    Outbox,
    ProactiveLoop,
    SchedulerEngine,
)
from cogito_agent.governance import AuditLogger, PolicyEngine, PolicyRule
from cogito_agent.shared import DecisionType, ScheduleJob
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository
from cogito_agent.trace import Tracer


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    return database


@pytest.fixture
def wid(db: Database) -> str:
    ws_id = "ws-autonomy"
    repo = WorkspaceRepository(db)
    repo.create(ws_id, "autonomy-test")
    return ws_id


@pytest.fixture
def permissive_policy() -> PolicyEngine:
    return PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.allow),
        ]
    )


@pytest.fixture
def deny_policy() -> PolicyEngine:
    return PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.deny),
        ]
    )


@pytest.fixture
def scheduler(db: Database) -> SchedulerEngine:
    return SchedulerEngine(db)


@pytest.fixture
def gate(db: Database, permissive_policy: PolicyEngine) -> NotificationGate:
    return NotificationGate(db, policy_engine=permissive_policy)


@pytest.fixture
def audit(db: Database) -> AuditLogger:
    return AuditLogger(db)


@pytest.fixture
def tracer(db: Database) -> Tracer:
    return Tracer(db)


@pytest.fixture
def decision_store(db: Database) -> DecisionStore:
    return DecisionStore(db)


@pytest.fixture
def outbox(db: Database) -> Outbox:
    return Outbox(db)


@pytest.fixture
def feedback_store(db: Database, audit: AuditLogger) -> FeedbackStore:
    return FeedbackStore(db, audit_logger=audit)


@pytest.fixture
def proactive_loop(
    db: Database,
    scheduler: SchedulerEngine,
    gate: NotificationGate,
    decision_store: DecisionStore,
    outbox: Outbox,
    feedback_store: FeedbackStore,
    tracer: Tracer,
    audit: AuditLogger,
    permissive_policy: PolicyEngine,
) -> ProactiveLoop:
    return ProactiveLoop(
        scheduler=scheduler,
        notification_gate=gate,
        decision_store=decision_store,
        outbox=outbox,
        feedback_store=feedback_store,
        tracer=tracer,
        audit_logger=audit,
        policy_engine=permissive_policy,
        db=db,
        tick_interval=30.0,
    )


@pytest.fixture
def sample_job(wid: str) -> ScheduleJob:
    return ScheduleJob(
        id=str(uuid.uuid4()),
        name="test-job",
        workspace_id=wid,
        capability_name="read_file",
        schedule_type="one_shot",
        run_at=None,
        dry_run=True,
    )
