from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.execution import (
    CapabilityExecutionRequest,
    GovernedCapabilityExecutor,
    default_guardians,
)
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.runs import RunRepository
from cogito_agent.shared import (
    DecisionType,
    JobStatus,
    PolicyRequest,
    ScheduleJob,
    SpanKind,
)
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository
from cogito_agent.trace import Tracer
from cogito_agent.workspace.artifacts import ArtifactService

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
        last_error=row.get("last_error"),
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
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self._db = db
        self._tracer = tracer or Tracer(db)
        self._audit = audit_logger or AuditLogger(db)
        self._policy = policy_engine or PolicyEngine()
        self._gate = notification_gate or NotificationGate(db)
        self._cap_reg = capability_registry or CapabilityRegistry()
        self._runs = RunRepository(db)
        self._worker_id = f"scheduler:{os.getpid()}"
        self._cap_executor = GovernedCapabilityExecutor(
            self._cap_reg,
            self._policy,
            approvals=ApprovalRepository(db),
            audit=self._audit,
            tracer=self._tracer,
            guardians=default_guardians(),
            artifact_writer=ArtifactService(db),
        )

    def schedule(self, job: ScheduleJob) -> str:
        now = datetime.now(UTC).isoformat()
        jid = job.id or str(uuid.uuid4())
        next_run = job.next_run_at or job.run_at or now
        self._db.connection.execute(
            "INSERT INTO scheduled_jobs"
            " (id, name, workspace_id, actor, capability_name, input_json,"
            " schedule_type, run_at, interval_seconds, max_retries, retry_count,"
            " quiet_hours_start, quiet_hours_end, timezone, enabled, dry_run,"
            " status, last_run_at, next_run_at, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                jid,
                job.name,
                job.workspace_id,
                job.actor,
                job.capability_name,
                job.input_json,
                job.schedule_type,
                job.run_at,
                job.interval_seconds,
                job.max_retries,
                job.retry_count,
                job.quiet_hours_start,
                job.quiet_hours_end,
                job.timezone,
                int(job.enabled),
                int(job.dry_run),
                job.status.value,
                job.last_run_at,
                next_run,
                now,
                now,
            ),
        )
        self._db.connection.commit()
        return jid

    def cancel(self, job_id: str) -> bool:
        cur = self._db.connection.execute(
            "UPDATE scheduled_jobs SET status = ?, enabled = 0, updated_at = ? WHERE id = ?",
            (JobStatus.cancelled.value, datetime.now(UTC).isoformat(), job_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def get_job(self, job_id: str) -> ScheduleJob | None:
        cur = self._db.connection.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_job(dict(row))

    def list_jobs(self, workspace_id: str) -> list[ScheduleJob]:
        if workspace_id == "*":
            cur = self._db.connection.execute(
                "SELECT * FROM scheduled_jobs ORDER BY created_at DESC",
            )
        else:
            cur = self._db.connection.execute(
                "SELECT * FROM scheduled_jobs WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            )
        return [_row_to_job(dict(r)) for r in cur.fetchall()]

    def get_job_failures(self, workspace_id: str, since: str) -> int:
        cur = self._db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM scheduled_jobs"
            " WHERE workspace_id = ? AND status = 'failed' AND updated_at >= ?",
            (workspace_id, since),
        )
        row = cur.fetchone()
        return row["cnt"] if row else 0

    def reset_job(self, job_id: str) -> bool:
        cur = self._db.connection.execute(
            "UPDATE scheduled_jobs"
            " SET status = ?, retry_count = 0, last_error = NULL, updated_at = ?"
            " WHERE id = ? AND status = 'running'",
            (JobStatus.pending.value, datetime.now(UTC).isoformat(), job_id),
        )
        self._db.connection.commit()
        return cur.rowcount > 0

    def tick(self) -> list[ScheduleJob]:
        self._recover_expired_runs()
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        cur = self._db.connection.execute(
            "SELECT * FROM scheduled_jobs"
            " WHERE enabled = 1 AND status IN ('pending', 'failed')"
            " AND (next_run_at IS NULL OR next_run_at <= ?)"
            " AND (run_at IS NULL OR run_at <= ?)"
            " ORDER BY next_run_at ASC",
            (now_iso, now_iso),
        )
        rows = cur.fetchall()
        processed: list[ScheduleJob] = []
        for row in rows:
            job = _row_to_job(dict(row))
            if not self._claim_job(job.id, now_iso):
                continue
            self._execute_job(job)
            processed.append(job)
        return processed

    def _claim_job(self, job_id: str, now_iso: str) -> bool:
        with self._db.connection:
            cursor = self._db.connection.execute(
                "UPDATE scheduled_jobs SET status=?, updated_at=?"
                " WHERE id=? AND enabled=1 AND status IN ('pending', 'failed')"
                " AND (next_run_at IS NULL OR next_run_at <= ?)"
                " AND (run_at IS NULL OR run_at <= ?)",
                (JobStatus.running.value, now_iso, job_id, now_iso, now_iso),
            )
        return cursor.rowcount == 1

    def _recover_expired_runs(self) -> None:
        abandoned = self._runs.abandon_expired(run_type="scheduled")
        if not abandoned:
            return
        with self._db.connection:
            self._db.connection.executemany(
                "UPDATE scheduled_jobs SET status='pending', updated_at=?"
                " WHERE id=? AND status='running'",
                [
                    (datetime.now(UTC).isoformat(), str(run["definition_id"]))
                    for run in abandoned
                    if run.get("run_type") == "scheduled"
                ],
            )

    def _execute_job(self, job: ScheduleJob) -> None:
        now = datetime.now(UTC)
        fire_at = job.next_run_at or job.run_at or now.isoformat()
        run = self._runs.create(
            run_type="scheduled",
            workspace_id=job.workspace_id,
            definition_id=job.id,
            idempotency_key=f"{job.id}:{fire_at}",
            scheduled_at=fire_at,
            max_attempts=max(1, job.max_retries + 1),
            input_data={
                "job_name": job.name,
                "capability_name": job.capability_name,
                "input_json": job.input_json,
            },
        )
        run_id = str(run["id"])
        if not self._runs.claim(run_id, worker_id=self._worker_id):
            with self._db.connection:
                self._db.connection.execute(
                    "UPDATE scheduled_jobs SET status='failed', last_error=?, updated_at=?"
                    " WHERE id=? AND status='running'",
                    ("run could not be claimed", now.isoformat(), job.id),
                )
            return

        if self._is_quiet_hours(job, now):
            self._db.connection.execute(
                "UPDATE scheduled_jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.skipped.value, now.isoformat(), job.id),
            )
            self._db.connection.commit()
            self._audit.log(
                actor_id=job.actor,
                action="job.skipped",
                resource=f"job:{job.id}",
                workspace_id=job.workspace_id,
                decision="deny",
                reason="quiet_hours",
                details=json.dumps({"job_name": job.name, "reason": "quiet_hours"}),
            )
            self._runs.finish(
                run_id,
                status="cancelled",
                error_code="quiet_hours",
                error_message="Execution skipped during quiet hours",
            )
            return

        req = PolicyRequest(
            actor_id=job.actor,
            capability_name=job.capability_name,
            resource="database" if job.actor == "maintenance" else "*",
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
            self._audit.log(
                actor_id=job.actor,
                action="job.skipped",
                resource=f"job:{job.id}",
                workspace_id=job.workspace_id,
                decision="deny",
                reason="policy_denied",
                details=json.dumps(
                    {
                        "job_name": job.name,
                        "policy_reason": decision.reason,
                    }
                ),
            )
            self._runs.finish(
                run_id,
                status="failed",
                error_code="policy_denied",
                error_message=decision.reason,
            )
            return

        self._db.connection.execute(
            "UPDATE scheduled_jobs SET status = ?, updated_at = ? WHERE id = ?",
            (JobStatus.running.value, now.isoformat(), job.id),
        )
        self._db.connection.commit()

        trace = self._tracer.create_trace(
            workspace_id=job.workspace_id,
            root_event_id=job.id,
        )
        self._runs.set_trace_id(run_id, trace.id)
        span = self._tracer.create_span(trace.id, f"job_{job.name}", SpanKind.scheduler)

        self._audit.log(
            actor_id=job.actor,
            action="execute",
            resource=f"job:{job.id}",
            workspace_id=job.workspace_id,
            trace_id=trace.id,
            decision=decision.decision.value,
            reason=decision.reason,
            details=json.dumps(
                {
                    "job_name": job.name,
                    "capability": job.capability_name,
                    "dry_run": job.dry_run,
                }
            ),
        )

        new_status = JobStatus.completed
        last_error: str | None = None
        if not job.dry_run:
            try:
                kwargs = json.loads(job.input_json) if job.input_json else {}
                execution = self._cap_executor.execute(
                    CapabilityExecutionRequest(
                        capability_name=job.capability_name,
                        arguments=kwargs,
                        actor_id=job.actor,
                        source="background",
                        workspace_id=job.workspace_id,
                        trace_id=trace.id,
                        span_id=span.id,
                        operation="execute",
                        resource="database" if job.actor == "maintenance" else "*",
                        idempotency_key=(
                            f"scheduled-job:{job.id}:{job.next_run_at or job.run_at or ''}"
                        ),
                    )
                )
                result = execution.tool_result
                if execution.status == "approval_required":
                    new_status = JobStatus.failed
                    last_error = f"approval_required:{execution.approval_id}"
                elif execution.status in {"denied", "not_found"}:
                    new_status = JobStatus.failed
                    last_error = execution.reason
                elif result is None:
                    new_status = JobStatus.failed
                    last_error = "capability returned None"
                elif result.status == "error":
                    new_status = JobStatus.failed
                    last_error = result.status
            except Exception as exc:
                new_status = JobStatus.failed
                last_error = str(exc)

            self._db.connection.execute(
                "UPDATE scheduled_jobs SET retry_count = retry_count + 1 WHERE id = ?",
                (job.id,),
            )
            self._db.connection.commit()

            if new_status == JobStatus.failed and job.retry_count < job.max_retries:
                retry_next = (now + timedelta(seconds=60 * (2**job.retry_count))).isoformat()
                self._db.connection.execute(
                    "UPDATE scheduled_jobs"
                    " SET status = ?, last_run_at = ?, next_run_at = ?,"
                    " updated_at = ?, retry_count = ?, last_error = ?"
                    " WHERE id = ?",
                    (
                        new_status.value,
                        now.isoformat(),
                        retry_next,
                        now.isoformat(),
                        job.retry_count + 1,
                        last_error,
                        job.id,
                    ),
                )
                self._db.connection.commit()
                self._tracer.end_span(span)
                self._tracer.end_trace(trace)
                self._runs.finish(
                    run_id,
                    status="failed",
                    error_code="capability_failed",
                    error_message=last_error or "Capability execution failed",
                )
                return

        self._tracer.end_span(span)
        self._tracer.end_trace(trace)

        final_next = self._compute_next_run(job, now) if new_status == JobStatus.completed else None
        self._db.connection.execute(
            "UPDATE scheduled_jobs"
            " SET status = ?, last_run_at = ?, next_run_at = ?,"
            " updated_at = ?, last_error = ?"
            " WHERE id = ?",
            (new_status.value, now.isoformat(), final_next, now.isoformat(), last_error, job.id),
        )
        self._db.connection.commit()
        self._runs.finish(
            run_id,
            status="succeeded" if new_status == JobStatus.completed else "failed",
            result_data={"job_status": new_status.value, "next_run_at": final_next or ""},
            error_code="" if new_status == JobStatus.completed else "capability_failed",
            error_message=last_error or "",
        )

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
