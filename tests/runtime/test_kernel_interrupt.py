from __future__ import annotations

from unittest.mock import MagicMock

from cogito_agent.models import ModelAdapter, ModelResponse
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import (
    EventSource,
    EventType,
    RuntimeEvent,
    TurnState,
)
from cogito_agent.storage import (
    Database,
    SessionRepository,
    WorkspaceRepository,
)


def _setup(db: Database) -> None:
    ws = WorkspaceRepository(db)
    ws.create("ws-1", "test")
    sess = SessionRepository(db)
    sess.create("sess-1", "ws-1", "test")


def _event() -> RuntimeEvent:
    return RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "hello"},
    )


def test_interrupt_persists_state(db: Database) -> None:
    _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(content="ok")
    kernel = RuntimeKernel(db, model_adapter=adapter)
    event = _event()
    kernel.interrupt(event)
    cur = db.connection.execute(
        "SELECT turn_state, model_call_count, tool_call_count"
        " FROM interrupted_turns ORDER BY rowid DESC LIMIT 1"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["turn_state"] == "interrupted"
    assert kernel.state == TurnState.interrupted


def test_resume_revalidates(db: Database) -> None:
    _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(content="ok")
    kernel = RuntimeKernel(db, model_adapter=adapter)
    event = _event()
    kernel.interrupt(event)
    result = kernel.resume(_event())
    assert result.state == TurnState.completed, f"Failed with error: {result.error}"


def test_interrupt_saves_event_json(db: Database) -> None:
    _setup(db)
    adapter = MagicMock(spec=ModelAdapter)
    adapter.chat.return_value = ModelResponse(content="ok")
    kernel = RuntimeKernel(db, model_adapter=adapter)
    event = _event()
    kernel.interrupt(event)
    cur = db.connection.execute(
        "SELECT event_json FROM interrupted_turns ORDER BY rowid DESC LIMIT 1"
    )
    row = cur.fetchone()
    assert row is not None
    import json
    saved = json.loads(row["event_json"])
    assert saved["workspace_id"] == "ws-1"
