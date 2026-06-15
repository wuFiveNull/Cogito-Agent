from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.shared import (
    DecisionType,
    JobStatus,
    PolicyRequest,
    ScheduleJob,
    SpanKind,
)
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer

from .gate import NotificationGate


def _row_to_job(row: dict[str, Any]) -> ScheduleJob:
    return ScheduleJob(
        id=row["id"],
        name=row["name"],
        workspace_id=row["workspace_id"],
        actor=row["actor"],
        capability_name=row["capability_name"],
        input_json=row["input_json"],
        schedule_type=row["schedule_type"],
        run_at=row.get("run_at"),
        interval_seconds=row.get("interval_seconds"),
        max_retries=row["max_retries"],
        retry_count=row["retry_count"],
        quiet_hours_start=row.get("quiet_hours_start"),
        quiet_hours_end=row.get("quiet_hours_end"),
        timezone=row["timezone"],
        enabled=bool(row["enabled"]),
        dry_run=bool(row["dry_run"]),
        status=JobStatus(row["status"]),
        last_run_at=row.get("last_run_at"),
        next_run_at=row.get("next_run_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SchedulerEngine:
    def __init__(
        self,
        db: Database,
        tracer: Tracer | None = None,
        audit_logger: AuditLogger | None = None,
        policy_engine: PolicyEngine | None = None,
        notification_gate: NotificationGate | None = None,
    ) -> None:
        self._db = db
        self._tracer = tracer or Tracer(db)
        self._audit = audit_logger or AuditLogger(db)
        self._policy = policy_engine or PolicyEngine()
        self._gate = notification_gate or NotificationGate(db)

    def schedule(self, job: ScheduleJob) -> str:
        now = datetime.now(UTC).isoformat()
        jid = job.id or str(uuid.uuid4())
        self._db.connection.execute(
            "INSERT INTO scheduled_jobs"
            " (id, name, workspace_id, actor, capability_name, input_json,"
            " schedule_type, run_at, interval_seconds, max_retries, retry_count,"
            " quiet_hours_start, quiet_hours_end, timezone, enabled, dry_run,"
            " status, last_run_at, next_run_at, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                jid, job.name, job.workspace_id, job.actor,
                job.capability_name, job.input_json,
                job.schedule_type, job.run_at, job.interval_seconds,
                job.max_retries, job.retry_count,
                job.quiet_hours_start, job.quiet_hours_end,
                job.timezone, int(job.enabled), int(job.dry_run),
                job.status.value, job.last_run_at, job.next_run_at,
                now, now,
            ),
        )
        self._db.connection.commit()
        return jid

    def cancel(self, job_id: str) -> None:
        self._db.connection.execute(
            "UPDATE scheduled_jobs SET enabled = 0, updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), job_id),
        )
        self._db.connection.commit()

    def get_job(self, job_id: str) -> ScheduleJob | None:
        cur = self._db.connection.execute(
            "SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_job(dict(row))

    def list_jobs(self, workspace_id: str) -> list[ScheduleJob]:
        cur = self._db.connection.execute(
            "SELECT * FROM scheduled_jobs WHERE workspace_id = ?"
            " ORDER BY created_at DESC",
            (workspace_id,),
        )
        return [_row_to_job(dict(r)) for r in cur.fetchall()]

    def tick(self) -> list[ScheduleJob]:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        cur = self._db.connection.execute(
            "SELECT * FROM scheduled_jobs"
            " WHERE enabled = 1 AND status IN ('pending', 'failed')"
            " AND (next_run_at IS NULL OR next_run_at <= ?)"
            " ORDER BY next_run_at ASC",
            (now_iso,),
        )
        rows = cur.fetchall()
        processed: list[ScheduleJob] = []
        for row in rows:
            job = _row_to_job(dict(row))
            self._execute_job(job)
            processed.append(job)
        return processed

    def _execute_job(self, job: ScheduleJob) -> None:
        now = datetime.now(UTC)

        if self._is_quiet_hours(job, now):
            self._db.connection.execute(
                "UPDATE scheduled_jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.skipped.value, now.isoformat(), job.id),
            )
            self._db.connection.commit()
            return

        req = PolicyRequest(
            actor_id=job.actor,
            capability_name=job.capability_name,
            resource="*",
            operation="execute",
            context="background",
        )
        decision = self._policy.evaluate(req)
        if decision.decision == DecisionType.deny:
            self._db.connection.execute(
                "UPDATE scheduled_jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.skipped.value, now.isoformat(), job.id),
            )
            self._db.connection.commit()
            return

        trace = self._tracer.create_trace(
            workspace_id=job.workspace_id,
            root_event_id=job.id,
        )
        span = self._tracer.create_span(
            trace.id, f"job_{job.name}", SpanKind.scheduler
        )

        self._audit.log(
            actor_id=job.actor,
            action="execute",
            resource=f"job:{job.id}",
            workspace_id=job.workspace_id,
            trace_id=trace.id,
            decision=decision.decision.value,
            reason=decision.reason,
            details=json.dumps({
                "job_name": job.name,
                "capability": job.capability_name,
                "dry_run": job.dry_run,
            }),
        )

        new_status = JobStatus.completed
        if not job.dry_run:
            try:
                self._db.connection.execute(
                    "UPDATE scheduled_jobs SET retry_count = retry_count + 1"
                    " WHERE id = ?",
                    (job.id,),
                )
                self._db.connection.commit()
            except Exception:
                new_status = JobStatus.failed

        self._tracer.end_span(span)
        self._tracer.end_trace(trace)

        next_run = self._compute_next_run(job, now)
        self._db.connection.execute(
            "UPDATE scheduled_jobs"
            " SET status = ?, last_run_at = ?, next_run_at = ?, updated_at = ?"
            " WHERE id = ?",
            (new_status.value, now.isoformat(), next_run, now.isoformat(), job.id),
        )
        self._db.connection.commit()

    def _is_quiet_hours(self, job: ScheduleJob, now: datetime) -> bool:
        start_str = job.quiet_hours_start
        end_str = job.quiet_hours_end
        if not start_str or not end_str:
            cur = self._db.connection.execute(
                "SELECT quiet_hours_start, quiet_hours_end FROM workspace_settings"
                " WHERE workspace_id = ?",
                (job.workspace_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            start_str = str(row["quiet_hours_start"] or "")
            end_str = str(row["quiet_hours_end"] or "")
        if not start_str or not end_str:
            return False
        current_time = now.strftime("%H:%M")
        if start_str <= end_str:
            return start_str <= current_time <= end_str
        return current_time >= start_str or current_time <= end_str

    @staticmethod
    def _compute_next_run(job: ScheduleJob, now: datetime) -> str | None:
        if job.schedule_type == "interval" and job.interval_seconds:
            from datetime import timedelta

            return (now + timedelta(seconds=job.interval_seconds)).isoformat()
        return None
