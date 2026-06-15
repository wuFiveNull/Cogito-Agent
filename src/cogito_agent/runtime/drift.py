from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from cogito_agent.shared import RuntimeEvent
from cogito_agent.storage import Database

from .kernel import RuntimeKernel, TurnResult


class DriftEvent:
    def __init__(
        self,
        event: RuntimeEvent,
        callback: Callable[[TurnResult], None] | None = None,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.event = event
        self.callback = callback
        self.created_at = datetime.now(UTC).isoformat()
        self.result: TurnResult | None = None


class DriftRuntime:
    def __init__(
        self,
        db: Database,
        kernel_factory: Callable[[], RuntimeKernel] | None = None,
        max_workers: int = 2,
    ) -> None:
        self._db = db
        self._kernel_factory = kernel_factory or (lambda: RuntimeKernel(db))
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="drift",
        )
        self._lock = threading.RLock()
        self._tasks: dict[str, DriftEvent] = {}

    def start(self) -> None:
        pass

    def stop(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def submit(
        self,
        event: RuntimeEvent,
        callback: Callable[[TurnResult], None] | None = None,
        timeout: float | None = None,
    ) -> str:
        drift_event = DriftEvent(event, callback)
        with self._lock:
            self._tasks[drift_event.id] = drift_event

        future = self._executor.submit(self._process, drift_event)
        if timeout is not None:
            future.result(timeout=timeout)
        return drift_event.id

    def get_result(self, task_id: str) -> TurnResult | None:
        with self._lock:
            event = self._tasks.get(task_id)
            if event is None:
                return None
            return event.result

    def task_status(self, task_id: str) -> str | None:
        with self._lock:
            event = self._tasks.get(task_id)
            if event is None:
                return None
            if event.result is None:
                return "pending"
            return "completed" if event.result.error is None else "failed"

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": eid,
                    "status": self.task_status(eid),
                    "created_at": e.created_at,
                }
                for eid, e in self._tasks.items()
            ]

    def _process(self, drift_event: DriftEvent) -> None:
        kernel = self._kernel_factory()
        result = kernel.process(drift_event.event)
        drift_event.result = result
        if drift_event.callback:
            try:
                drift_event.callback(result)
            except Exception:
                pass
