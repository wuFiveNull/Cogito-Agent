from __future__ import annotations

from cogito_agent.autonomy import NotificationGate, ProactiveEngine, SchedulerEngine
from cogito_agent.shared import ScheduleJob
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


def _setup(db: Database) -> None:
    db.initialize()
    db.migrate()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-loop", "loop-test")


def test_run_once_no_jobs() -> None:
    db = Database(":memory:")
    _setup(db)
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, tick_interval=1.0)

    results = engine.run_once()
    assert results == []


def test_run_once_processes_due_job() -> None:
    db = Database(":memory:")
    _setup(db)
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)

    from datetime import UTC, datetime, timedelta

    job = ScheduleJob(
        id="test-job-1",
        name="test-job",
        workspace_id="ws-loop",
        actor="scheduler",
        capability_name="read_file",
        input_json="{}",
        schedule_type="one_shot",
        run_at=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
    )
    scheduler.schedule(job)

    engine = ProactiveEngine(scheduler, gate, tick_interval=1.0)
    results = engine.run_once()
    assert len(results) == 1
    assert "test-job" in results[0]


def test_run_once_skips_future_job() -> None:
    db = Database(":memory:")
    _setup(db)
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)

    from datetime import UTC, datetime, timedelta

    job = ScheduleJob(
        id="future-job-1",
        name="future-job",
        workspace_id="ws-loop",
        actor="scheduler",
        capability_name="read_file",
        input_json="{}",
        schedule_type="one_shot",
        run_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat(),
    )
    scheduler.schedule(job)

    engine = ProactiveEngine(scheduler, gate, tick_interval=1.0)
    results = engine.run_once()
    assert results == []


def test_stop() -> None:
    db = Database(":memory:")
    _setup(db)
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, tick_interval=0.1)

    import threading

    raised: list[Exception] = []

    def _run() -> None:
        try:
            engine.run()
        except Exception as e:
            raised.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    import time
    time.sleep(0.3)
    engine.stop()
    t.join(timeout=2.0)
    assert not raised, f"Unexpected exception: {raised}"
