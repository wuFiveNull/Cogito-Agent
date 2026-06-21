from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from cogito_agent.shared import JobStatus, ScheduleJob


def test_cancel_sets_status_cancelled(scheduler, wid: str) -> None:
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="cancel-status",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
    )
    jid = scheduler.schedule(job)
    scheduler.cancel(jid)
    saved = scheduler.get_job(jid)
    assert saved is not None
    assert saved.status == JobStatus.cancelled


def test_cancel_sets_enabled_false(scheduler, wid: str) -> None:
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="cancel-disabled",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
    )
    jid = scheduler.schedule(job)
    scheduler.cancel(jid)
    saved = scheduler.get_job(jid)
    assert saved is not None
    assert saved.enabled is False


def test_cancelled_job_not_ticked(scheduler, wid: str) -> None:
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="cancelled-no-tick",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
        next_run_at=past,
    )
    jid = scheduler.schedule(job)
    scheduler.cancel(jid)
    processed = scheduler.tick()
    cancelled_ids = [j.id for j in processed]
    assert jid not in cancelled_ids


def test_cancel_nonexistent_returns_false(scheduler, wid: str) -> None:
    result = scheduler.cancel("nonexistent-job")
    assert result is False


def test_get_job_failures_counts(scheduler, wid: str) -> None:
    recent = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "fail-recent-1", wid, "read_file", JobStatus.failed.value, recent),
    )
    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "fail-recent-2", wid, "read_file", JobStatus.failed.value, recent),
    )
    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "fail-old", wid, "read_file", JobStatus.failed.value, old),
    )
    scheduler._db.connection.commit()

    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    count = scheduler.get_job_failures(wid, since)
    assert count == 2


def test_get_job_failures_empty(scheduler, wid: str) -> None:
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    count = scheduler.get_job_failures(wid, since)
    assert count == 0


def test_get_job_failures_other_status_ignored(scheduler, wid: str) -> None:
    recent = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "completed-job", wid, "read_file", JobStatus.completed.value, recent),
    )
    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), "running-job", wid, "read_file", JobStatus.running.value, recent),
    )
    scheduler._db.connection.commit()

    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    count = scheduler.get_job_failures(wid, since)
    assert count == 0


def test_reset_job_resets_to_pending(scheduler, wid: str) -> None:
    jid = str(uuid.uuid4())
    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, retry_count, last_error)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (jid, "reset-me", wid, "read_file", JobStatus.running.value, 3, "some error"),
    )
    scheduler._db.connection.commit()

    result = scheduler.reset_job(jid)
    assert result is True

    saved = scheduler.get_job(jid)
    assert saved is not None
    assert saved.status == JobStatus.pending
    assert saved.retry_count == 0
    assert saved.last_error is None


def test_reset_job_non_running_not_reset(scheduler, wid: str) -> None:
    jid = str(uuid.uuid4())
    scheduler._db.connection.execute(
        "INSERT INTO scheduled_jobs"
        " (id, name, workspace_id, capability_name, status, retry_count, last_error)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (jid, "no-reset", wid, "read_file", JobStatus.completed.value, 2, "err"),
    )
    scheduler._db.connection.commit()

    result = scheduler.reset_job(jid)
    assert result is False

    saved = scheduler.get_job(jid)
    assert saved is not None
    assert saved.status == JobStatus.completed
    assert saved.retry_count == 2
    assert saved.last_error == "err"


def test_reset_job_nonexistent_returns_false(scheduler, wid: str) -> None:
    result = scheduler.reset_job("nonexistent-job")
    assert result is False
