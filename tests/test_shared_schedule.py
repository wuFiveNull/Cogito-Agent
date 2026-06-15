from __future__ import annotations

from cogito_agent.shared import JobStatus, ScheduleJob


def test_schedule_job_defaults() -> None:
    job = ScheduleJob(
        id="j1",
        name="test",
        workspace_id="ws1",
        capability_name="read_file",
    )
    assert job.actor == "scheduler"
    assert job.schedule_type == "one_shot"
    assert job.dry_run is True
    assert job.status == JobStatus.pending
    assert job.enabled is True
    assert job.max_retries == 0


def test_job_status_values() -> None:
    assert JobStatus.pending.value == "pending"
    assert JobStatus.running.value == "running"
    assert JobStatus.completed.value == "completed"
    assert JobStatus.failed.value == "failed"
    assert JobStatus.skipped.value == "skipped"


def test_schedule_job_interval() -> None:
    job = ScheduleJob(
        id="j2",
        name="interval-job",
        workspace_id="ws1",
        capability_name="list_files",
        schedule_type="interval",
        interval_seconds=3600,
    )
    assert job.schedule_type == "interval"
    assert job.interval_seconds == 3600


def test_schedule_job_with_quiet_hours() -> None:
    job = ScheduleJob(
        id="j3",
        name="quiet-job",
        workspace_id="ws1",
        capability_name="notify",
        quiet_hours_start="22:00",
        quiet_hours_end="08:00",
    )
    assert job.quiet_hours_start == "22:00"
    assert job.quiet_hours_end == "08:00"
    assert job.timezone == "UTC"
