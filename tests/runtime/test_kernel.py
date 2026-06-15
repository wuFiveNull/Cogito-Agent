from cogito_agent.runtime import RuntimeKernel, TurnBudget
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, TurnState
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


def test_kernel_user_message(db: Database) -> None:
    _setup(db)
    kernel = RuntimeKernel(db)
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "hello"},
    )
    result = kernel.process(event)
    assert result.state == TurnState.completed
    assert "hello" in result.output


def test_kernel_empty_message(db: Database) -> None:
    _setup(db)
    kernel = RuntimeKernel(db)
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": ""},
    )
    result = kernel.process(event)
    assert result.state == TurnState.completed
    assert "I didn't receive" in result.output


def test_kernel_persists_message(db: Database) -> None:
    _setup(db)
    kernel = RuntimeKernel(db)
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "hi"},
    )
    kernel.process(event)
    cur = db.connection.execute(
        "SELECT content FROM messages WHERE session_id = ?",
        ("sess-1",),
    )
    rows = cur.fetchall()
    assert len(rows) >= 1
    assert any("hi" in r["content"] for r in rows)


def test_kernel_with_custom_budget(db: Database) -> None:
    _setup(db)
    budget = TurnBudget(max_model_calls=3, max_tool_calls=5)
    kernel = RuntimeKernel(db, budget=budget)
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="user-1",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": "test"},
    )
    result = kernel.process(event)
    assert result.state == TurnState.completed


def test_kernel_state_transitions(db: Database) -> None:
    kernel = RuntimeKernel(db)
    assert kernel.state == TurnState.received


def test_kernel_tool_result_event(db: Database) -> None:
    _setup(db)
    kernel = RuntimeKernel(db)
    event = RuntimeEvent(
        workspace_id="ws-1",
        session_id="sess-1",
        actor_id="tool",
        source=EventSource.cli,
        type=EventType.tool_result,
        payload={"result": "ok"},
    )
    result = kernel.process(event)
    assert result.state == TurnState.completed
