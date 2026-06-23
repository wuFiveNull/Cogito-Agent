from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database
from cogito_agent.storage.repositories import DaemonStateRepository as _DaemonStateRepository

from .gate import NotificationGate
from .scheduler import SchedulerEngine


class ProactiveEngine:
    def __init__(
        self,
        scheduler: SchedulerEngine,
        notification_gate: NotificationGate,
        db: Database | None = None,
        tick_interval: float = 30.0,
    ) -> None:
        self._scheduler = scheduler
        self._gate = notification_gate
        self._db = db
        self._daemon_repo = _DaemonStateRepository(db) if db is not None else None
        self._tick_interval = tick_interval
        self._running = False

    def _update_state(self, **kwargs: str | None) -> None:
        if not kwargs or self._daemon_repo is None:
            return
        self._daemon_repo.update(**kwargs)

    def run(self) -> None:
        self._running = True
        started = datetime.now(UTC)
        started_iso = started.isoformat()
        print(f"[daemon] Proactive engine started at {started_iso}")
        print(f"[daemon] Tick interval: {self._tick_interval}s")

        if self._daemon_repo is not None:
            row = self._daemon_repo.get()
            if row and row.get("status") == "running":
                print("[daemon] WARNING: Previous instance may have crashed")
                self._update_state(
                    status="running",
                    started_at=started_iso,
                    last_heartbeat=started_iso,
                    crash_marker="recovered",
                )
            else:
                self._update_state(
                    status="running",
                    started_at=started_iso,
                    last_heartbeat=started_iso,
                )

        heartbeat_counter = 0
        try:
            while self._running:
                tick_start = time.time()
                try:
                    processed = self._scheduler.tick()
                    if processed:
                        for job in processed:
                            print(f"[daemon] Job '{job.name}' ({job.id[:8]}): {job.status.value}")
                except Exception as exc:
                    print(f"[daemon] Tick error: {exc}")

                heartbeat_counter += 1
                if heartbeat_counter % 10 == 0 and self._db is not None:
                    self._update_state(last_heartbeat=datetime.now(UTC).isoformat())

                elapsed = time.time() - tick_start
                sleep_time = max(0.1, self._tick_interval - elapsed)
                time.sleep(sleep_time)
        except BaseException:
            if self._db is not None:
                stopped = datetime.now(UTC).isoformat()
                self._update_state(
                    status="stopped",
                    stopped_at=stopped,
                    crash_marker="crash",
                )
            raise
        finally:
            if self._db is not None:
                stopped = datetime.now(UTC).isoformat()
                self._update_state(
                    status="stopped",
                    stopped_at=stopped,
                    graceful_shutdown_marker="true",
                )
            print("[daemon] Proactive engine stopped.")

    def stop(self) -> None:
        self._running = False

    def run_once(self) -> list[str]:
        processed = self._scheduler.tick()
        return [f"{j.name} ({j.id[:8]}): {j.status.value}" for j in processed]

    @staticmethod
    def load_status(db: Database) -> dict[str, Any]:
        repo = _DaemonStateRepository(db)
        row = repo.get()
        if row is None:
            return {"status": "stopped", "started_at": None, "last_heartbeat": None}
        cur = db.connection.execute("SELECT * FROM daemon_state WHERE id = 'main'")
        row = cur.fetchone()
        return dict(row) if row else {"status": "stopped", "started_at": None, "last_heartbeat": None}
