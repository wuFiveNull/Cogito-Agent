from __future__ import annotations

import math
import random
import threading
import time as _time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol

from cogito_agent.shared import RuntimeEvent, SpanKind

from .kernel import RuntimeKernel, TurnResult
from .ports import DurableRunProvider, RuntimeServicesProvider
from .presence import PresenceStore


class DriftDatabasePort(RuntimeServicesProvider, DurableRunProvider, Protocol):
    @property
    def connection(self) -> Any: ...


LOW_RISK_MAINTENANCE_SKILLS: list[str] = [
    "memory_consolidation",
    "trace_review",
    "inbox_digest",
]

MEDIUM_RISK_SKILLS: list[str] = [
    "daily_brief",
    "task_extraction",
]

DEFAULT_QUIET_HOURS_START = "22:00"
DEFAULT_QUIET_HOURS_END = "07:00"
DEFAULT_DAILY_BUDGET = 5
DEFAULT_COOLDOWN_SECONDS = 300
DEFAULT_TICK_INTERVAL = 60

# ── Energy model (Akashic-style multi-timescale exponential decay) ───────


def compute_energy(
    last_user_at: datetime | None,
    now: datetime | None = None,
    *,
    alpha: float = 0.50,
    beta: float = 0.35,
    gamma: float = 0.15,
    tau1_min: float = 30.0,
    tau2_min: float = 240.0,
    tau3_min: float = 2880.0,
) -> float:
    """Return current energy in [0, 1].

    Three timescales capture short/medium/long-term user absence:
      - 30 min: conversation warmth
      - 240 min (4h): same-day context
      - 2880 min (48h): relationship continuity

    Never interacted → energy = 0.0 (always trigger).
    """
    if last_user_at is None:
        return 0.0
    now = now or datetime.now(UTC)
    t = max(0.0, (now - last_user_at).total_seconds() / 60.0)
    return (
        alpha * math.exp(-t / tau1_min)
        + beta * math.exp(-t / tau2_min)
        + gamma * math.exp(-t / tau3_min)
    )


def d_energy(energy: float) -> float:
    """Interaction hunger: lower energy → higher hunger → higher trigger chance."""
    return 1.0 - max(0.0, min(1.0, energy))


def _next_interval_from_energy(
    energy: float,
    *,
    tick_s1: int = 2400,
    tick_s0: int = 4800,
    jitter: float = 0.3,
) -> int:
    """Adaptive tick interval based on current energy.

    Higher energy (user just chatted) → longer interval → less frequent ticks.
    Lower energy (user absent) → shorter interval → more frequent ticks.
    """
    base_score = d_energy(energy)
    base = tick_s1 if base_score > 0.20 else tick_s0
    if jitter <= 0:
        return base
    r = random.uniform(1.0 - jitter, 1.0 + jitter)
    return max(60, int(base * r))


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
        db: DriftDatabasePort,
        kernel_factory: Callable[[], RuntimeKernel] | None = None,
        max_workers: int = 2,
        *,
        kernel: RuntimeKernel | None = None,
    ) -> None:
        """Background autonomy runtime for proactive skills.

        Args:
            db: Database port.
            kernel_factory: Factory for creating new kernels per skill run.
                Ignored when ``kernel`` is provided.
            max_workers: Thread pool size.
            kernel: **Shared** RuntimeKernel instance (e.g. the API singleton).
                When set, ``DriftConsumer`` uses this kernel instead of creating
                a new one per task, and ``kernel_factory`` is NOT used.
        """
        self._db = db
        self._kernel = kernel  # shared kernel (optional)
        self._kernel_factory = kernel_factory or (
            lambda: RuntimeKernel(db.create_runtime_services())
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="drift",
        )
        self._lock = threading.RLock()
        self._tasks: dict[str, DriftEvent] = {}
        self._last_run: dict[str, float] = {}
        self._tick_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_user_at: datetime | None = None
        self._presence = PresenceStore(db)
        runtime_services = db.create_runtime_services()
        self._tracer = runtime_services.tracer
        self._audit = runtime_services.audit
        self._runs = db.create_run_repository()
        self._worker_id = f"drift:{uuid.uuid4()}"
        # Drift consumer for queue-based task execution
        self._drift_queue = DriftTaskQueue(db)
        consumer_kernel_factory: Callable[[], RuntimeKernel] = (
            (lambda: kernel) if kernel is not None else self._kernel_factory
        )
        self._consumer = DriftConsumer(
            self._drift_queue,
            consumer_kernel_factory,
        )

    def start(self) -> None:
        self._ensure_state()
        self._recover_expired_runs()
        # Start the background DriftConsumer for queue-based task execution
        self._consumer.start()
        if self._tick_thread is None or not self._tick_thread.is_alive():
            self._stop_event.clear()
            self._tick_thread = threading.Thread(
                target=self._tick_loop,
                daemon=True,
                name="drift-tick",
            )
            self._tick_thread.start()

    def stop(self, wait: bool = True) -> None:
        self._stop_event.set()
        self._consumer.stop()
        self._executor.shutdown(wait=wait)
        if self._tick_thread and self._tick_thread.is_alive():
            self._tick_thread.join(timeout=5)

    def _ensure_state(self) -> None:
        self._db.connection.execute("INSERT OR IGNORE INTO drift_state (id) VALUES ('main')")
        self._db.connection.commit()
        # Read last activity from PresenceStore (single source of truth)
        self._last_user_at = self._presence.get_last_user_at("default")

    # ── Tick Loop ─────────────────────────────────────────────────────────

    def _tick_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                pass
            # Adaptive interval: higher energy (user active) → sleep longer
            energy = compute_energy(self._last_user_at)
            interval = _next_interval_from_energy(energy)
            self._stop_event.wait(interval)

    def update_last_user_at(self, dt: datetime | None = None) -> None:
        """Record user activity time. Delegates to PresenceStore (single source of truth)."""
        self._last_user_at = dt or datetime.now(UTC)
        try:
            self._presence.touch("default", channel="drift", now=self._last_user_at)
        except Exception:
            pass

    def _tick(self) -> None:
        state = self._get_state()
        if not state.get("enabled") or state.get("paused"):
            return

        if self._in_quiet_hours(state):
            return

        daily_budget = int(str(state.get("daily_budget", DEFAULT_DAILY_BUDGET)))
        runs_today = int(str(state.get("runs_today", 0)))
        if runs_today >= daily_budget:
            return

        pending = self._runs.list_runs(
            workspace_id="default",
            status="pending",
            run_type="drift",
            limit=1,
        )
        if pending:
            self._execute_skill_runtime(
                str(pending[0]["definition_id"]),
                state,
                durable_run_id=str(pending[0]["id"]),
            )
            return

        eligible = self._select_eligible_skills()
        if not eligible:
            return

        skill_name = eligible[0]
        self._execute_skill_runtime(skill_name, state)

    def _get_state(self) -> dict[str, object]:
        cur = self._db.connection.execute("SELECT * FROM drift_state WHERE id = 'main'")
        row = cur.fetchone()
        return dict(row) if row else {}

    def _in_quiet_hours(self, state: dict[str, object]) -> bool:
        qh_start = str(state.get("quiet_hours_start", DEFAULT_QUIET_HOURS_START))
        qh_end = str(state.get("quiet_hours_end", DEFAULT_QUIET_HOURS_END))
        if not qh_start and not qh_end:
            return False
        try:
            now = datetime.now(UTC)
            current = now.strftime("%H:%M")
            if qh_start <= qh_end:
                return qh_start <= current <= qh_end
            return current >= qh_start or current <= qh_end
        except Exception:
            return False

    def _select_eligible_skills(self) -> list[str]:
        """Energy-aware skill selection.

        When energy is low (user absent), pick the skill that hasn't been
        run for the longest. When energy is high (user just chatted),
        pick the least intrusive skill.
        """
        energy = compute_energy(self._last_user_at)
        is_low_energy = d_energy(energy) > 0.5

        candidates: list[tuple[str, float]] = []
        for skill in LOW_RISK_MAINTENANCE_SKILLS:
            last = self._last_run.get(skill, 0.0)
            elapsed = _time.time() - last
            if elapsed >= DEFAULT_COOLDOWN_SECONDS:
                candidates.append((skill, -elapsed if is_low_energy else elapsed))

        if not candidates:
            for skill in MEDIUM_RISK_SKILLS:
                last = self._last_run.get(skill, 0.0)
                elapsed = _time.time() - last
                if elapsed >= DEFAULT_COOLDOWN_SECONDS * 2:
                    candidates.append((skill, -elapsed if is_low_energy else elapsed))

        if not candidates:
            return []

        # Sort: when low energy, prefer most-stale skill; when high energy, prefer most-recent
        candidates.sort(key=lambda x: x[1], reverse=is_low_energy)
        return [skill for skill, _ in candidates]

    def _execute_skill_runtime(
        self,
        skill_name: str,
        state: dict[str, object],
        durable_run_id: str | None = None,
    ) -> dict[str, object]:
        workspace_id = "default"
        self._last_run[skill_name] = _time.time()

        if durable_run_id is None:
            durable = self._runs.create(
                run_type="drift",
                workspace_id=workspace_id,
                definition_id=skill_name,
                max_attempts=3,
                input_data={"source": "drift_tick"},
            )
            run_id = str(durable["id"])
        else:
            run_id = durable_run_id
        if not self._runs.claim(run_id, worker_id=self._worker_id):
            return {
                "run_id": run_id,
                "skill_name": skill_name,
                "status": "not_claimed",
            }

        trace = self._tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id=f"drift_{skill_name}",
            session_id="",
        )
        trace_id = trace.id
        self._runs.set_trace_id(run_id, trace_id)
        span = self._tracer.create_span(trace_id, f"drift_{skill_name}", SpanKind.autonomous)

        result: dict[str, object] = {
            "run_id": run_id,
            "skill_name": skill_name,
            "trace_id": trace_id,
            "status": "running",
        }

        try:
            skill_result = self._invoke_skill(skill_name, workspace_id, trace_id)
            result.update(skill_result)
            result["status"] = "completed"

            span.output_summary = f"drift {skill_name} completed"
            self._tracer.end_span(span)
            self._tracer.end_trace(trace)

            raw_aid = skill_result.get("artifact_id")
            artifact_id = str(raw_aid) if isinstance(raw_aid, str) else ""
            audit_id = self._audit.log(
                actor_id="drift",
                action=f"drift.run.{skill_name}",
                resource=f"drift_run:{run_id}",
                workspace_id=workspace_id,
                trace_id=trace_id,
                decision="allow",
                reason=f"Drift run of {skill_name} completed",
                redact_details=True,
            )

            self._persist_run(
                run_id, workspace_id, skill_name, "completed", trace_id, audit_id, artifact_id
            )
            if artifact_id:
                self._runs.add_output(run_id, "artifact", artifact_id)
            self._runs.finish(
                run_id,
                status="succeeded",
                result_data=skill_result,
            )
            self._increment_runs_today()

            return result

        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            span.output_summary = f"drift {skill_name} failed: {exc}"
            self._tracer.end_span(span)
            self._tracer.end_trace(trace)

            audit_id = self._audit.log(
                actor_id="drift",
                action=f"drift.run.{skill_name}",
                resource=f"drift_run:{run_id}",
                workspace_id=workspace_id,
                trace_id=trace_id,
                decision="deny",
                reason=f"Drift run of {skill_name} failed: {exc}",
                redact_details=True,
            )

            self._persist_run(
                run_id, workspace_id, skill_name, "failed", trace_id, audit_id, "", str(exc)
            )
            self._runs.finish(
                run_id,
                status="failed",
                error_code="drift_skill_failed",
                error_message=str(exc),
            )
            return result

    def _recover_expired_runs(self) -> None:
        for run in self._runs.abandon_expired(run_type="drift"):
            self._runs.retry(str(run["id"]))

    def _invoke_skill(self, skill_name: str, workspace_id: str, trace_id: str) -> dict[str, object]:
        from cogito_agent.skill.builtin import (
            run_daily_brief,
            run_inbox_digest,
            run_memory_consolidation,
            run_task_extraction,
            run_trace_review,
        )

        runners: dict[str, Any] = {
            "daily_brief": run_daily_brief,
            "memory_consolidation": run_memory_consolidation,
            "task_extraction": run_task_extraction,
            "trace_review": run_trace_review,
            "inbox_digest": run_inbox_digest,
        }

        fn = runners.get(skill_name)
        if fn is None:
            raise ValueError(f"Unknown drift skill: {skill_name}")

        result = fn(
            db=self._db,
            workspace_id=workspace_id,
            session_id="",
            trace_id=trace_id,
        )
        if not isinstance(result, dict):
            raise TypeError(f"Drift skill {skill_name} returned a non-dict result")
        return result

    def _persist_run(
        self,
        run_id: str,
        workspace_id: str,
        skill_name: str,
        status: str,
        trace_id: str,
        audit_id: str,
        artifact_id: str,
        error_message: str = "",
    ) -> None:
        self._db.connection.execute(
            "INSERT INTO drift_runs"
            " (id, workspace_id, skill_name, status, trace_id, audit_id,"
            " artifact_id, started_at, completed_at, error_message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)"
            " ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
            " trace_id=excluded.trace_id, audit_id=excluded.audit_id,"
            " artifact_id=excluded.artifact_id,"
            " completed_at=datetime('now'), error_message=excluded.error_message",
            (
                run_id,
                workspace_id,
                skill_name,
                status,
                trace_id,
                audit_id,
                artifact_id,
                error_message,
            ),
        )
        self._db.connection.commit()

    def _increment_runs_today(self) -> None:
        self._db.connection.execute(
            "UPDATE drift_state SET runs_today = runs_today + 1,"
            " updated_at = datetime('now') WHERE id = 'main'"
        )
        self._db.connection.commit()

    # ── Public API ──────────────────────────────────────────────────────────

    def pause(self, reason: str = "") -> None:
        self._db.connection.execute(
            "UPDATE drift_state SET paused = 1, paused_at = datetime('now'),"
            " pause_reason = ?, updated_at = datetime('now') WHERE id = 'main'",
            (reason,),
        )
        self._db.connection.commit()

    def resume(self) -> None:
        self._db.connection.execute(
            "UPDATE drift_state SET paused = 0, pause_reason = '',"
            " updated_at = datetime('now') WHERE id = 'main'"
        )
        self._db.connection.commit()

    def is_paused(self) -> bool:
        state = self._get_state()
        return bool(state.get("paused", False))

    def is_enabled(self) -> bool:
        state = self._get_state()
        return bool(state.get("enabled", True))

    def status(self) -> dict[str, object]:
        state = self._get_state()
        now = datetime.now(UTC)
        enabled = bool(state.get("enabled", True))
        paused = bool(state.get("paused", False))
        daily_budget = int(str(state.get("daily_budget", DEFAULT_DAILY_BUDGET)))
        runs_today = int(str(state.get("runs_today", 0)))
        last_tick = str(state.get("last_tick_at", ""))
        qh_start = str(state.get("quiet_hours_start", DEFAULT_QUIET_HOURS_START))
        qh_end = str(state.get("quiet_hours_end", DEFAULT_QUIET_HOURS_END))
        in_quiet = self._in_quiet_hours(state)
        eligible = self._select_eligible_skills()

        return {
            "enabled": enabled,
            "paused": paused,
            "quiet_hours_start": qh_start,
            "quiet_hours_end": qh_end,
            "in_quiet_hours": in_quiet,
            "daily_budget": daily_budget,
            "runs_today": runs_today,
            "budget_remaining": max(0, daily_budget - runs_today),
            "last_tick": last_tick,
            "next_eligible_skills": eligible[:3],
            "pause_reason": str(state.get("pause_reason", "")),
            "paused_at": str(state.get("paused_at", "")),
            "timestamp": now.isoformat(),
        }

    def list_runs(self, workspace_id: str = "default", limit: int = 50) -> list[dict[str, object]]:
        cur = self._db.connection.execute(
            "SELECT * FROM drift_runs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_run(self, run_id: str) -> dict[str, object] | None:
        cur = self._db.connection.execute("SELECT * FROM drift_runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def reset_daily_budget(self) -> None:
        self._db.connection.execute(
            "UPDATE drift_state SET runs_today = 0, updated_at = datetime('now') WHERE id = 'main'"
        )
        self._db.connection.commit()

    def update_settings(self, **kwargs: Any) -> None:
        sets: list[str] = []
        params: list[object] = []
        for key, value in kwargs.items():
            if key in (
                "quiet_hours_start",
                "quiet_hours_end",
                "daily_budget",
                "timezone",
                "enabled",
                "paused",
            ):
                sets.append(f"{key} = ?")
                params.append(value)
        if sets:
            params.append(datetime.now(UTC).isoformat())
            self._db.connection.execute(
                f"UPDATE drift_state SET {', '.join(sets)},"  # noqa: S608
                " updated_at = ? WHERE id = 'main'",
                params,
            )
            self._db.connection.commit()

    # ── Legacy backward-compat methods ─────────────────────────────────────

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

    def __init__(self, db: DriftDatabasePort) -> None:
        self._db = db

    def consolidate_memories(self, workspace_id: str | None = None) -> int:
        """Delegate to ``MemoryMaintenance`` in the memory layer."""
        from cogito_agent.memory.maintenance import MemoryMaintenance

        return MemoryMaintenance(self._db).consolidate_legacy_memories(workspace_id)

    def archive_stale_memories(self, days: int = 30) -> int:
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
                    mid,
                    row["workspace_id"],
                    row["type"],
                    row["text"],
                    row["summary"],
                    row["confidence"],
                    row["sensitivity"],
                    row["source_id"],
                ),
            )
            archived += 1
        if archived:
            self._db.connection.commit()
        return archived

    def refresh_fts(self) -> int:
        self._db.connection.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
        self._db.connection.commit()
        cur = self._db.connection.execute("SELECT COUNT(*) as cnt FROM memories_fts")
        return int(cur.fetchone()["cnt"])

    def cleanup_traces(self, days: int = 90) -> dict[str, int]:
        old_traces = self._db.connection.execute(
            "SELECT id FROM traces WHERE started_at < datetime('now', ?)",
            (f"-{days} days",),
        ).fetchall()
        trace_ids = [r["id"] for r in old_traces]
        if not trace_ids:
            return {"traces": 0, "spans": 0, "tool_calls": 0, "model_calls": 0}
        placeholders = ",".join("?" for _ in trace_ids)
        tables = ["spans", "tool_calls", "model_calls", "source_lineage", "context_items"]
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
        def _exec(sql: str, params: tuple[object, ...] = ()) -> int:
            return int(self._db.connection.execute(sql, params).fetchone()[0])

        if workspace_id:
            msg_count = _exec(
                "SELECT COUNT(*) FROM messages WHERE workspace_id = ?",
                (workspace_id,),
            )
            mem_count = _exec(
                "SELECT COUNT(*) FROM memories WHERE workspace_id = ?"
                " AND deleted_at IS NULL AND status != 'stale'",
                (workspace_id,),
            )
            trace_count = _exec(
                "SELECT COUNT(*) FROM traces WHERE workspace_id = ?",
                (workspace_id,),
            )
            tool_count = _exec(
                "SELECT COUNT(*) FROM tool_calls tc"
                " JOIN traces t ON tc.trace_id = t.id"
                " WHERE t.workspace_id = ?",
                (workspace_id,),
            )
            audit_count = _exec(
                "SELECT COUNT(*) FROM audit_logs WHERE workspace_id = ?",
                (workspace_id,),
            )
        else:
            msg_count = _exec("SELECT COUNT(*) FROM messages")
            mem_count = _exec(
                "SELECT COUNT(*) FROM memories WHERE deleted_at IS NULL AND status != 'stale'",
            )
            trace_count = _exec("SELECT COUNT(*) FROM traces")
            tool_count = _exec("SELECT COUNT(*) FROM tool_calls")
            audit_count = _exec("SELECT COUNT(*) FROM audit_logs")

        return {
            "workspace_id": workspace_id or "*",
            "messages": msg_count,
            "memories": mem_count,
            "traces": trace_count,
            "tool_calls": tool_count,
            "audit_logs": audit_count,
        }


# ── DriftTaskQueue ────────────────────────────────────────────────────
# Lightweight queue for Drift tasks, separate from user-facing MessageQueue.
# Uses InputQueueRepository with task_type='drift_task' for persistence.


class DriftTaskQueue:
    """Thread-safe queue for Drift background tasks.

    Unlike the user-facing ``MessageQueue``, this does NOT use an in-memory
    ``asyncio.Queue`` — Drift runs on threads, not asyncio.  It relies on
    the SQLite ``input_queue`` table for persistence and status tracking.
    """

    DRIFT_TASK_TYPE = "drift_task"

    def __init__(self, db: Any) -> None:
        from cogito_agent.storage.input_queue_repository import InputQueueRepository

        self._repo = InputQueueRepository(db)

    def enqueue(self, msg: "InboundMessage") -> str:
        """Persist a drift task to the input_queue table."""
        return self._repo.insert(msg, task_type=self.DRIFT_TASK_TYPE)

    def claim_pending(self, limit: int = 5) -> list["InboundMessage"]:
        """Claim the next batch of pending drift tasks.

        Returns pending messages and resets stale ``processing`` entries.
        """
        from cogito_agent.storage.input_queue_repository import InputQueueRepository as _IR

        rows = self._repo.list_by_task_type(self.DRIFT_TASK_TYPE, "pending", limit=limit)
        if not rows:
            # Also recover stale processing entries
            rows = self._repo.list_by_task_type(
                self.DRIFT_TASK_TYPE, "processing", limit=limit
            )
            # Reset them to pending (same logic as InputQueueRepository.recover_pending)
            from datetime import timedelta

            timeout = datetime.now(UTC) - timedelta(seconds=300)
            timeout_str = timeout.strftime("%Y-%m-%d %H:%M:%S")
            stale = [
                r for r in rows
                if r.get("started_at") and str(r["started_at"]) < timeout_str
            ]
            rows = stale
            for r in rows:
                self._repo.update_status(str(r["id"]), "pending")
            if not rows:
                return []
        return [_IR.row_to_inbound(r) for r in rows]

    def mark_processing(self, qid: str) -> None:
        self._repo.update_status(qid, "processing")

    def mark_done(self, qid: str) -> None:
        self._repo.update_status(qid, "done")

    def mark_failed(self, qid: str, error: str = "") -> None:
        self._repo.update_status(qid, "failed", error=error)


# ── DriftConsumer ─────────────────────────────────────────────────────


class DriftConsumer:
    """Background thread consumer for Drift tasks.

    Polls ``DriftTaskQueue`` periodically and processes each task through
    a shared ``RuntimeKernel`` (when available) or a freshly created one.
    """

    def __init__(
        self,
        queue: DriftTaskQueue,
        kernel_factory: Callable[[], RuntimeKernel],
        *,
        poll_interval: float = 1.0,
        max_tasks_per_cycle: int = 5,
    ) -> None:
        self._queue = queue
        self._kernel_factory = kernel_factory
        self._poll_interval = poll_interval
        self._max_tasks = max_tasks_per_cycle
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="drift-consumer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    def _run_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                tasks = self._queue.claim_pending(limit=self._max_tasks)
                for inbound in tasks:
                    qid = str(inbound.metadata.get("queue_id", ""))
                    if not qid:
                        continue
                    self._queue.mark_processing(qid)
                    try:
                        kernel = self._kernel_factory()
                        from cogito_agent.runtime.kernel import RuntimeKernel as _RK

                        event = _RK._inbound_to_event(inbound)
                        kernel.process(event)
                        self._queue.mark_done(qid)
                    except Exception as exc:
                        self._queue.mark_failed(qid, str(exc))
            except Exception:
                pass  # Don't let one bad cycle kill the consumer
            self._stop_event.wait(self._poll_interval)
