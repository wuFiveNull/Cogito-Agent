from __future__ import annotations

import uuid

from cogito_agent.shared import JobStatus, ScheduleJob


def test_schedule_one_shot(scheduler, wid: str) -> None:
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="test-one-shot",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
    )
    jid = scheduler.schedule(job)
    saved = scheduler.get_job(jid)
    assert saved is not None
    assert saved.name == "test-one-shot"
    assert saved.status == JobStatus.pending
    assert saved.enabled is True


def test_schedule_then_cancel(scheduler, wid: str) -> None:
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="cancel-me",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
    )
    jid = scheduler.schedule(job)
    scheduler.cancel(jid)
    saved = scheduler.get_job(jid)
    assert saved is not None
    assert saved.enabled is False


def test_tick_processes_due_jobs(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="due-job",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
        next_run_at=past,
    )
    scheduler.schedule(job)
    processed = scheduler.tick()
    assert len(processed) == 1
    assert processed[0].name == "due-job"
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status in (JobStatus.completed,)


def test_tick_skips_future_jobs(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta

    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="future-job",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
        next_run_at=future,
    )
    scheduler.schedule(job)
    processed = scheduler.tick()
    assert len(processed) == 0


def test_tick_respects_quiet_hours(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    scheduler._gate.set_quiet_hours(wid, start="00:00", end="23:59")
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="quiet-job",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
        next_run_at=past,
    )
    scheduler.schedule(job)
    processed = scheduler.tick()
    assert len(processed) == 1
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.skipped


def test_list_jobs(scheduler, wid: str) -> None:
    j1 = ScheduleJob(id=str(uuid.uuid4()), name="a", workspace_id=wid, capability_name="read_file")
    j2 = ScheduleJob(id=str(uuid.uuid4()), name="b", workspace_id=wid, capability_name="list_files")
    scheduler.schedule(j1)
    scheduler.schedule(j2)
    jobs = scheduler.list_jobs(wid)
    assert len(jobs) == 2
    names = {j.name for j in jobs}
    assert names == {"a", "b"}


def test_interval_job_computes_next_run(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta

    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="interval-job",
        workspace_id=wid,
        capability_name="read_file",
        schedule_type="interval",
        interval_seconds=300,
        dry_run=True,
        next_run_at=past,
    )
    scheduler.schedule(job)
    processed = scheduler.tick()
    assert len(processed) == 1
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.completed
    assert saved.next_run_at is not None
