from __future__ import annotations

import time
from datetime import UTC, datetime

from .gate import NotificationGate
from .scheduler import SchedulerEngine


class ProactiveEngine:
    def __init__(
        self,
        scheduler: SchedulerEngine,
        notification_gate: NotificationGate,
        tick_interval: float = 30.0,
    ) -> None:
        self._scheduler = scheduler
        self._gate = notification_gate
        self._tick_interval = tick_interval
        self._running = False

    def run(self) -> None:
        self._running = True
        started = datetime.now(UTC)
        print(f"[daemon] Proactive engine started at {started.isoformat()}")
        print(f"[daemon] Tick interval: {self._tick_interval}s")

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

            elapsed = time.time() - tick_start
            sleep_time = max(0.1, self._tick_interval - elapsed)
            time.sleep(sleep_time)

        print("[daemon] Proactive engine stopped.")

    def stop(self) -> None:
        self._running = False

    def run_once(self) -> list[str]:
        processed = self._scheduler.tick()
        return [f"{j.name} ({j.id[:8]}): {j.status.value}" for j in processed]
