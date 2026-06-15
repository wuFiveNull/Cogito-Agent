from __future__ import annotations

from cogito_agent.runtime import DriftRuntime
from cogito_agent.runtime.drift import DriftEvent
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository


def _setup(db: Database) -> None:
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-drift", "drift-test")
    sess_repo = SessionRepository(db)
    sess_repo.create("sess-1", "ws-drift", "test")


def test_process_directly() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "direct"},
    )

    drift_event = DriftEvent(event)
    engine._process(drift_event)
    assert drift_event.result is not None
    assert drift_event.result.error is None


def test_submit_via_executor() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "via executor"},
    )

    task_id = engine.submit(event, timeout=5.0)
    assert task_id is not None
    result = engine.get_result(task_id)
    assert result is not None
    assert result.error is None
    assert "via executor" in result.output or result.output == ""

    engine.stop()


def test_submit_with_callback() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    callback_results: list[str] = []

    def _callback(result: object) -> None:
        callback_results.append("called")

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "callback test"},
    )

    task_id = engine.submit(event, callback=_callback, timeout=5.0)
    assert task_id is not None
    assert callback_results == ["called"]

    engine.stop()


def test_list_tasks() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "list test"},
    )

    task_id = engine.submit(event, timeout=5.0)
    assert task_id is not None

    tasks = engine.list_tasks()
    assert len(tasks) >= 1
    matching = [t for t in tasks if t["id"] == task_id]
    assert len(matching) == 1
    assert matching[0]["status"] in ("completed", "failed")

    engine.stop()


def test_get_nonexistent_task() -> None:
    engine = DriftRuntime(Database(":memory:"))
    assert engine.get_result("nonexistent") is None
    assert engine.task_status("nonexistent") is None
