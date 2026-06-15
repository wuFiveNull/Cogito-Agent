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


class DriftMaintenance:
    """Background maintenance tasks: dedup, archival, FTS refresh, trace cleanup, usage reports."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def consolidate_memories(self, workspace_id: str | None = None) -> int:
        """Deduplicate memories with identical text in the same workspace."""
        if workspace_id:
            rows = self._db.connection.execute(
                "SELECT id, text, workspace_id, rowid FROM memories"
                " WHERE deleted_at IS NULL AND workspace_id = ?"
                " ORDER BY text, created_at ASC", (workspace_id,)
            ).fetchall()
        else:
            rows = self._db.connection.execute(
                "SELECT id, text, workspace_id, rowid FROM memories"
                " WHERE deleted_at IS NULL"
                " ORDER BY text, created_at ASC"
            ).fetchall()
        removed = 0
        seen: dict[str, list[dict[str, object]]] = {}
        for r in rows:
            text = str(r["text"])
            if text not in seen:
                seen[text] = [dict(r)]
            else:
                seen[text].append(dict(r))
        for text, group in seen.items():
            if len(group) <= 1:
                continue
            for dup in group[1:]:
                mid = dup["id"]
                wid = str(dup["workspace_id"])
                rowid = dup["rowid"]
                self._db.connection.execute(
                    "DELETE FROM memories_fts WHERE rowid = ?", (rowid,)
                )
                self._db.connection.execute(
                    "DELETE FROM memories WHERE id = ? AND workspace_id = ?",
                    (mid, wid),
                )
                removed += 1
        if removed:
            self._db.connection.commit()
        return removed

    def archive_stale_memories(self, days: int = 30) -> int:
        """Mark memories older than *days* with status='stale'."""
        import uuid
        stale = self._db.connection.execute(
            "SELECT id, workspace_id, type, text, summary, confidence,"
            " sensitivity, source_id FROM memories"
            " WHERE deleted_at IS NULL AND status != 'stale'"
            " AND created_at < datetime('now', ?)",
            (f"-{days} days",),
        ).fetchall()
        archived = 0
        for row in stale:
            mid = str(uuid.uuid4())
            self._db.connection.execute(
                "INSERT INTO memories"
                " (id, workspace_id, type, status, text, summary, confidence,"
                " sensitivity, source_id, created_at, updated_at)"
                " VALUES (?, ?, ?, 'stale', ?, ?, ?, ?, ?,"
                " datetime('now'), datetime('now'))",
                (
                    mid, row["workspace_id"], row["type"],
                    row["text"], row["summary"],
                    row["confidence"], row["sensitivity"],
                    row["source_id"],
                ),
            )
            archived += 1
        if archived:
            self._db.connection.commit()
        return archived

    def refresh_fts(self) -> int:
        """Rebuild memory FTS index."""
        self._db.connection.execute(
            "INSERT INTO memories_fts(memories_fts) VALUES('rebuild')"
        )
        self._db.connection.commit()
        cur = self._db.connection.execute(
            "SELECT COUNT(*) as cnt FROM memories_fts"
        )
        return int(cur.fetchone()["cnt"])

    def cleanup_traces(self, days: int = 90) -> dict[str, int]:
        """Delete traces older than *days* and their child records."""
        old_traces = self._db.connection.execute(
            "SELECT id FROM traces"
            " WHERE started_at < datetime('now', ?)",
            (f"-{days} days",),
        ).fetchall()
        trace_ids = [r["id"] for r in old_traces]
        if not trace_ids:
            return {"traces": 0, "spans": 0, "tool_calls": 0, "model_calls": 0}
        placeholders = ",".join("?" for _ in trace_ids)
        tables = ["spans", "tool_calls", "model_calls",
                  "source_lineage", "context_items"]
        counts: dict[str, int] = {"traces": len(trace_ids)}
        for table in tables:
            cur = self._db.connection.execute(
                f"DELETE FROM {table} WHERE trace_id IN ({placeholders})",  # noqa: S608
                trace_ids,
            )
            counts[table] = cur.rowcount
        cur = self._db.connection.execute(
            f"DELETE FROM traces WHERE id IN ({placeholders})",  # noqa: S608
            trace_ids,
        )
        self._db.connection.commit()
        return counts

    def usage_report(self, workspace_id: str | None = None) -> dict[str, object]:
        """Return aggregate usage statistics."""
        ws_filter = "WHERE workspace_id = ?" if workspace_id else ""
        params = (workspace_id,) if workspace_id else ()

        msg_count = self._db.connection.execute(
            f"SELECT COUNT(*) FROM messages {ws_filter}", params
        ).fetchone()[0]
        mem_count = self._db.connection.execute(
            f"SELECT COUNT(*) FROM memories"
            f" {ws_filter} AND deleted_at IS NULL AND status != 'stale'", params
        ).fetchone()[0]
        trace_count = self._db.connection.execute(
            f"SELECT COUNT(*) FROM traces {ws_filter}", params
        ).fetchone()[0]
        if workspace_id:
            tool_count = self._db.connection.execute(
                "SELECT COUNT(*) FROM tool_calls tc"
                " JOIN traces t ON tc.trace_id = t.id"
                " WHERE t.workspace_id = ?", (workspace_id,)
            ).fetchone()[0]
        else:
            tool_count = self._db.connection.execute(
                "SELECT COUNT(*) FROM tool_calls"
            ).fetchone()[0]
        audit_count = self._db.connection.execute(
            f"SELECT COUNT(*) FROM audit_logs {ws_filter}", params
        ).fetchone()[0]

        return {
            "workspace_id": workspace_id or "*",
            "messages": int(msg_count),
            "memories": int(mem_count),
            "traces": int(trace_count),
            "tool_calls": int(tool_count),
            "audit_logs": int(audit_count),
        }
