from __future__ import annotations

import argparse
import os
import signal
import threading
from pathlib import Path

from cogito_agent.autonomy import NotificationGate, ProactiveEngine, SchedulerEngine
from cogito_agent.config import Settings, load_config
from cogito_agent.logging import setup_logging
from cogito_agent.storage import Database

from .maintenance import MaintenanceWorker
from .process import AlreadyRunningError, PidFile


def _default_pid_path(db_path: str) -> str:
    if db_path == ":memory:":
        return os.path.expanduser("~/.cogito/cogito.pid")
    return str(Path(db_path).expanduser().resolve().with_name("cogito.pid"))


def run_daemon(
    db_path: str | None = None,
    tick_interval: float = 30.0,
    pid_path: str | None = None,
    stop_event: threading.Event | None = None,
) -> int:
    """Run the local daemon until interrupted, returning a process exit code."""
    config = load_config()
    resolved_db = os.path.expanduser(db_path or config.storage.db_path)
    resolved_pid = pid_path or _default_pid_path(resolved_db)
    setup_logging(config.logging)

    guard = PidFile(resolved_pid)
    try:
        guard.acquire()
    except AlreadyRunningError as exc:
        print(f"[daemon] {exc}")
        return 2

    db = Database(resolved_db)
    db.initialize()
    db.migrate()
    scheduler = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(scheduler, gate, db=db, tick_interval=tick_interval)
    maintenance = MaintenanceWorker(config.storage)
    maintenance_thread = threading.Thread(target=maintenance.run, daemon=True)
    maintenance_thread.start()

    def _stop(signum: int, _frame: object) -> None:
        print(f"\n[daemon] Signal {signum} received, shutting down...")
        engine.stop()

    def _reload(_signum: int, _frame: object) -> None:
        Settings.reload()
        print("[daemon] Configuration reloaded.")

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _reload)

    if stop_event is not None:
        def _watch_stop_event() -> None:
            stop_event.wait()
            engine.stop()

        threading.Thread(target=_watch_stop_event, daemon=True).start()

    try:
        engine.run()
    except KeyboardInterrupt:
        engine.stop()
    finally:
        maintenance.stop()
        db.close()
        guard.release()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="cogito-daemon")
    parser.add_argument("--db", dest="db_path", help="SQLite database path")
    parser.add_argument("--pid-file", dest="pid_path", help="PID file path")
    parser.add_argument("--tick-interval", type=float, default=30.0)
    args = parser.parse_args()
    raise SystemExit(run_daemon(args.db_path, args.tick_interval, args.pid_path))


__all__ = ["main", "run_daemon"]


if __name__ == "__main__":
    main()
