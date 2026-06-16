from __future__ import annotations

from cogito_agent.autonomy import NotificationGate, ProactiveEngine, SchedulerEngine
from cogito_agent.storage import Database


def test_load_status_empty(db: Database) -> None:
    status = ProactiveEngine.load_status(db)
    assert status["status"] == "stopped"
    assert status["started_at"] is None
    assert status["last_heartbeat"] is None


def test_run_once_does_not_write_state(db: Database, wid: str) -> None:
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, db=db, tick_interval=0.1)
    engine.run_once()
    status = ProactiveEngine.load_status(db)
    assert status["status"] == "stopped"
    assert status["started_at"] is None


def test_run_captures_running_state(db: Database, wid: str) -> None:
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, db=db, tick_interval=0.1)

    import threading
    import time

    t = threading.Thread(target=engine.run, daemon=True)
    t.start()
    time.sleep(0.3)

    status = ProactiveEngine.load_status(db)
    assert status["status"] == "running"
    assert status["started_at"] is not None
    assert status["last_heartbeat"] is not None

    engine.stop()
    t.join(timeout=2.0)


def test_heartbeat_updates_during_run(db: Database, wid: str) -> None:
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, db=db, tick_interval=0.05)

    import threading
    import time

    t = threading.Thread(target=engine.run, daemon=True)
    t.start()
    time.sleep(1.0)

    status1 = ProactiveEngine.load_status(db)
    hb1 = status1["last_heartbeat"]

    time.sleep(1.0)
    status2 = ProactiveEngine.load_status(db)
    hb2 = status2["last_heartbeat"]
    assert hb2 >= hb1

    engine.stop()
    t.join(timeout=2.0)


def test_load_status_after_stop(db: Database, wid: str) -> None:
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, db=db, tick_interval=0.1)

    import threading
    import time

    t = threading.Thread(target=engine.run, daemon=True)
    t.start()
    time.sleep(0.3)
    engine.stop()
    t.join(timeout=2.0)

    status = ProactiveEngine.load_status(db)
    assert status["status"] == "stopped"
