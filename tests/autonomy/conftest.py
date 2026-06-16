from __future__ import annotations

import uuid

import pytest

from cogito_agent.autonomy import NotificationGate, SchedulerEngine
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.shared import DecisionType, ScheduleJob
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


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
    return PolicyEngine(rules=[
        PolicyRule("*", "*", "*", DecisionType.allow),
    ])


@pytest.fixture
def scheduler(db: Database) -> SchedulerEngine:
    return SchedulerEngine(db)


@pytest.fixture
def gate(db: Database, permissive_policy: PolicyEngine) -> NotificationGate:
    return NotificationGate(db, policy_engine=permissive_policy)


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
