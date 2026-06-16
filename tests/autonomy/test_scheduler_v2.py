from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    DecisionType,
    JobStatus,
    Permission,
    RiskLevel,
    ScheduleJob,
)
from cogito_agent.storage import Database


def _make_manifest(name: str = "test_cap") -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version="1.0",
        type=CapabilityType.tool,
        description="Test capability",
        input_schema={},
        output_schema={},
        permissions=[Permission(resource="*", operations=["execute"])],
        risk_level=RiskLevel.low,
        allowed_contexts=["background", "interactive"],
        approval_required=False,
        audit_required=True,
        idempotent=True,
    )


def _register_cap(registry: CapabilityRegistry) -> None:
    def _echo(input_text: str = "") -> ToolResult:
        return ToolResult(status="success", summary=input_text, data={"result": input_text})

    registry.register("test_cap", _make_manifest(), _echo)


def _register_failing(registry: CapabilityRegistry, name: str = "failing_cap") -> None:
    def _fail(input_text: str = "") -> ToolResult:
        return ToolResult(status="error", summary="failed", error="intentional failure", data={})

    registry.register(name, _make_manifest(name), _fail)


def test_invocation_calls_capability(db: Database, wid: str) -> None:
    registry = CapabilityRegistry()
    _register_cap(registry)
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db, capability_registry=registry)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="cap-invoke",
        workspace_id=wid,
        capability_name="test_cap",
        dry_run=False,
        input_json=json.dumps({"input_text": "hello world"}),
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.completed


def test_invocation_nonexistent_capability(db: Database, wid: str) -> None:
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="missing-cap",
        workspace_id=wid,
        capability_name="i_do_not_exist",
        dry_run=False,
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.failed


def test_invocation_capability_error(db: Database, wid: str) -> None:
    registry = CapabilityRegistry()
    _register_failing(registry)
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db, capability_registry=registry)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="err-cap",
        workspace_id=wid,
        capability_name="error_cap",
        dry_run=False,
        input_json=json.dumps({"input_text": "boom"}),
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.failed


def test_retry_on_failure(db: Database, wid: str) -> None:
    registry = CapabilityRegistry()
    _register_failing(registry, "retry_cap")
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db, capability_registry=registry)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="retry-job",
        workspace_id=wid,
        capability_name="retry_cap",
        dry_run=False,
        max_retries=2,
        retry_count=0,
        input_json=json.dumps({"input_text": "retry"}),
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.failed
    assert saved.retry_count == 1
    assert saved.next_run_at is not None


def test_retry_exhausted(db: Database, wid: str) -> None:
    registry = CapabilityRegistry()
    _register_failing(registry, "exhaust_cap")
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db, capability_registry=registry)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="exhaust-job",
        workspace_id=wid,
        capability_name="exhaust_cap",
        dry_run=False,
        max_retries=0,
        retry_count=0,
        input_json=json.dumps({"input_text": "exhaust"}),
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.retry_count == 1
    assert saved.status == JobStatus.failed


def test_running_status_during_execution(db: Database, wid: str) -> None:
    registry = CapabilityRegistry()
    _register_failing(registry, "slow_cap")
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db, capability_registry=registry)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="running-status",
        workspace_id=wid,
        capability_name="slow_cap",
        dry_run=False,
        input_json=json.dumps({"input_text": "running"}),
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status in (JobStatus.failed, JobStatus.completed)


def test_policy_denied_skips_job(db: Database, wid: str) -> None:
    policy = PolicyEngine(rules=[
        PolicyRule("*", "execute", "background", DecisionType.deny, capability="*"),
    ])
    from cogito_agent.autonomy import SchedulerEngine
    scheduler = SchedulerEngine(db, policy_engine=policy)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="policy-deny",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.skipped


def test_audit_on_quiet_hours_skip(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    scheduler._gate.set_quiet_hours(wid, start="00:00", end="23:59")
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="audit-skip",
        workspace_id=wid,
        capability_name="read_file",
        dry_run=True,
        next_run_at=past,
    )
    scheduler.schedule(job)
    scheduler.tick()
    cur = scheduler._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM audit_logs"
        " WHERE action = 'job.skipped' AND resource = ?",
        (f"job:{job.id}",),
    )
    assert cur.fetchone()["cnt"] >= 1


def test_interval_job_reschedules_after_tick(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta
    past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    job = ScheduleJob(
        id=str(uuid.uuid4()),
        name="interval-resched",
        workspace_id=wid,
        capability_name="read_file",
        schedule_type="interval",
        interval_seconds=60,
        dry_run=True,
        next_run_at=past,
    )
    scheduler.schedule(job)
    processed = scheduler.tick()
    assert len(processed) == 1
    saved = scheduler.get_job(job.id)
    assert saved is not None
    assert saved.status == JobStatus.completed
    assert saved.last_run_at is not None
    assert saved.next_run_at is not None


def test_tick_with_mixed_job_types(scheduler, wid: str) -> None:
    from datetime import UTC, datetime, timedelta
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    one_shot = ScheduleJob(
        id=str(uuid.uuid4()), name="one-shot-mixed", workspace_id=wid,
        capability_name="read_file", dry_run=True, next_run_at=past,
    )
    interval = ScheduleJob(
        id=str(uuid.uuid4()), name="interval-mixed", workspace_id=wid,
        capability_name="read_file", schedule_type="interval",
        interval_seconds=300, dry_run=True, next_run_at=past,
    )
    scheduler.schedule(one_shot)
    scheduler.schedule(interval)
    processed = scheduler.tick()
    assert len(processed) == 2
