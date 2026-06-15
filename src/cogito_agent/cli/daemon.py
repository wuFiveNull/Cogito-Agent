from __future__ import annotations

import signal
import sys

from cogito_agent.autonomy import NotificationGate, ProactiveEngine, SchedulerEngine
from cogito_agent.storage import Database


def run_daemon(db_path: str = ":memory:", tick_interval: float = 30.0) -> None:
    db = Database(db_path)
    db.initialize()

    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, tick_interval)

    def _handle_signal(signum: int, _frame: object) -> None:
        print(f"\n[daemon] Signal {signum} received, shutting down...")
        engine.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        engine.run()
    except KeyboardInterrupt:
        engine.stop()
    finally:
        db.close()

    sys.exit(0)
