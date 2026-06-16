from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from cogito_agent.storage import Database

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
        self._tick_interval = tick_interval
        self._running = False

    def _update_state(self, **kwargs: str | None) -> None:
        if not kwargs or self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        vals = list(kwargs.values())
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        self._db.connection.execute(
            f"INSERT INTO daemon_state (id, {cols}, updated_at)"
            f" VALUES ('main', {placeholders}, ?)"
            f" ON CONFLICT(id) DO UPDATE SET {set_clause}, updated_at = ?",
            [*vals, now, now],
        )
        self._db.connection.commit()

    def run(self) -> None:
        self._running = True
        started = datetime.now(UTC)
        started_iso = started.isoformat()
        print(f"[daemon] Proactive engine started at {started_iso}")
        print(f"[daemon] Tick interval: {self._tick_interval}s")

        if self._db is not None:
            cur = self._db.connection.execute(
                "SELECT status, crash_marker FROM daemon_state WHERE id = 'main'"
            )
            row = cur.fetchone()
            if row and row["status"] == "running":
                print("[daemon] WARNING: Previous instance may have crashed")
                self._update_state(
                    status="running", started_at=started_iso,
                    last_heartbeat=started_iso, crash_marker="recovered",
                )
            else:
                self._update_state(
                    status="running", started_at=started_iso,
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
                            print(
                                f"[daemon] Job '{job.name}' "
                                f"({job.id[:8]}): {job.status.value}"
                            )
                except Exception as exc:
                    print(f"[daemon] Tick error: {exc}")

                heartbeat_counter += 1
                if heartbeat_counter % 10 == 0 and self._db is not None:
                    self._update_state(
                        last_heartbeat=datetime.now(UTC).isoformat()
                    )

                elapsed = time.time() - tick_start
                sleep_time = max(0.1, self._tick_interval - elapsed)
                time.sleep(sleep_time)
        except BaseException:
            if self._db is not None:
                stopped = datetime.now(UTC).isoformat()
                self._update_state(
                    status="stopped", stopped_at=stopped, crash_marker="crash",
                )
            raise
        finally:
            if self._db is not None:
                stopped = datetime.now(UTC).isoformat()
                self._update_state(
                    status="stopped", stopped_at=stopped,
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
        cur = db.connection.execute(
            "SELECT * FROM daemon_state WHERE id = 'main'"
        )
        row = cur.fetchone()
        if row is None:
            return {"status": "stopped", "started_at": None, "last_heartbeat": None}
        return dict(row)
