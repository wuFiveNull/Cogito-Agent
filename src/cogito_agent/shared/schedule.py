from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class ScheduleJob(BaseModel):
    id: str
    name: str
    workspace_id: str
    actor: str = "scheduler"
    capability_name: str
    input_json: str = "{}"
    schedule_type: str = "one_shot"
    run_at: str | None = None
    interval_seconds: int | None = None
    max_retries: int = 0
    retry_count: int = 0
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str = "UTC"
    enabled: bool = True
    dry_run: bool = True
    status: JobStatus = JobStatus.pending
    last_error: str | None = None
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
