from __future__ import annotations

import pytest

from cogito_agent.storage import Database


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    return database
