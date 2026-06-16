from __future__ import annotations

import pytest

from cogito_agent.skill import SkillRunner
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    return database


@pytest.fixture
def db_ws(db: Database) -> Database:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-run", "test-runner")
    ws_repo.create("ws-err", "test-error")
    ws_repo.create("ws-skip", "test-skip")
    return db


@pytest.fixture
def db_runner(db_ws: Database) -> SkillRunner:
    return SkillRunner(db_ws)


@pytest.fixture
def db_with_ws(db_ws: Database) -> SkillRunner:
    return SkillRunner(db_ws)
