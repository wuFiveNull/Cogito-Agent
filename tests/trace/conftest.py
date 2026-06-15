from __future__ import annotations

import pytest

from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database


@pytest.fixture
def tracer(db: Database) -> Tracer:
    return Tracer(db)
