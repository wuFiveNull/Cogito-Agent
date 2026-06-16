from __future__ import annotations

from cogito_agent.autonomy import ProactiveEngine, SchedulerEngine
from cogito_agent.autonomy.gate import NotificationGate
from cogito_agent.shared import JobStatus, ScheduleJob
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


def _seed_schedule_job(db: Database) -> str:
    from cogito_agent.shared import ScheduleJob

    ws_repo = WorkspaceRepository(db)
    ws = ws_repo.create("ws_sched", "ScheduleTest")
    ws_id = str(ws["id"])

    job = ScheduleJob(
        id="sched_job_test",
        name="test_job",
        workspace_id=ws_id,
        actor="maintenance",
        capability_name="maintenance.consolidate",
        input_json='{"workspace_id": "*"}',
        schedule_type="one_shot",
        run_at="2020-01-01T00:00:00",
        enabled=True,
        dry_run=True,
        max_retries=0,
        retry_count=0,
        status=JobStatus.pending,
    )
    sched = SchedulerEngine(db)
    jid = sched.schedule(job)
    return jid


def _db_init() -> Database:
    db = Database()
    db.initialize()
    db.migrate()
    return db


def test_schedule_list_empty() -> None:
    db = _db_init()
    sched = SchedulerEngine(db)
    jobs = sched.list_jobs("*")
    assert isinstance(jobs, list)
    assert len(jobs) == 0


def test_schedule_list_with_job() -> None:
    db = _db_init()
    jid = _seed_schedule_job(db)
    sched = SchedulerEngine(db)
    jobs = sched.list_jobs("*")
    my_jobs = [j for j in jobs if j.id == jid]
    assert len(my_jobs) >= 1
    assert my_jobs[0].name == "test_job"


def test_daemon_once_no_jobs() -> None:
    db = _db_init()
    sched = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(sched, gate)
    results = engine.run_once()
    assert isinstance(results, list)
    assert len(results) == 0


def test_daemon_once_with_job() -> None:
    db = _db_init()
    _seed_schedule_job(db)
    sched = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(sched, gate)
    results = engine.run_once()
    assert len(results) >= 1


def test_schedule_maintenance_creates_trace_and_audit() -> None:
    db = _db_init()
    ws_repo = WorkspaceRepository(db)
    ws = ws_repo.create("ws_trace_audit", "TraceAudit")
    ws_id = str(ws["id"])

    job = ScheduleJob(
        id="sched_trace_test",
        name="maintenance.usage",
        workspace_id=ws_id,
        actor="maintenance",
        capability_name="maintenance.usage",
        input_json="{}",
        schedule_type="one_shot",
        run_at="2020-01-01T00:00:00",
        enabled=True,
        dry_run=True,
        max_retries=0,
        retry_count=0,
        status=JobStatus.pending,
    )
    sched = SchedulerEngine(db)
    sched.schedule(job)
    gate = NotificationGate(db)
    engine = ProactiveEngine(sched, gate)
    engine.run_once()

    cur = db.connection.execute(
        "SELECT COUNT(*) as cnt FROM traces WHERE root_event_id = ?",
        ("sched_trace_test",),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["cnt"] >= 1

    cur = db.connection.execute(
        "SELECT COUNT(*) as cnt FROM audit_logs WHERE trace_id IN"
        " (SELECT id FROM traces WHERE root_event_id = ?)",
        ("sched_trace_test",),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["cnt"] >= 1


def test_schedule_duplicate_prevention() -> None:
    db = _db_init()
    _seed_schedule_job(db)
    sched = SchedulerEngine(db)
    gate = NotificationGate(db)
    engine = ProactiveEngine(sched, gate)

    engine.run_once()
    results = engine.run_once()
    sched_job = sched.get_job("sched_job_test")
    assert sched_job is not None
    assert sched_job.status in (JobStatus.completed, JobStatus.skipped)
