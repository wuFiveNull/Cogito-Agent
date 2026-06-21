from __future__ import annotations

from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner
from cogito_agent.storage.repositories import ApprovalRepository


def _run_and_get_ids(db_runner: SkillRunner, manifest: SkillManifest) -> tuple[str, str]:
    """Run a skill manifest and return (run_log_id, approval_id)."""
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"
    approval_id = log.step_logs[-1]["output"]
    assert approval_id != ""

    cur = db_runner._db.connection.execute(
        "SELECT id FROM skill_run_logs WHERE trace_id = ?",
        (log.trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    run_log_id = str(row["id"])
    return run_log_id, approval_id


def _make_manifest(name: str = "resume-test") -> SkillManifest:
    return SkillManifest(
        name=name,
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="c1",
                name="condition-true",
                kind=StepKind.condition,
                condition_expression="1 == 1",
            ),
            SkillStep(
                id="a1",
                name="approve-me",
                kind=StepKind.approval,
            ),
            SkillStep(
                id="t1",
                name="transform-after",
                kind=StepKind.transform,
                input_mapping={"out": "ran-after-approval"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )


def test_resume_approved_completes_skill(db_runner: SkillRunner) -> None:
    """Resume after approval is approved returns completed status."""
    manifest = _make_manifest("resume-approved-complete")
    run_log_id, approval_id = _run_and_get_ids(db_runner, manifest)

    repo = ApprovalRepository(db_runner._db)
    repo.resolve(approval_id, "approved", "test")

    log = db_runner.resume(run_log_id, approval_id)
    assert log is not None
    assert log.status == "completed"


def test_resume_approved_executes_remaining_steps(db_runner: SkillRunner) -> None:
    """Resume after approval is approved executes remaining steps."""
    manifest = _make_manifest("resume-approved-steps")
    run_log_id, approval_id = _run_and_get_ids(db_runner, manifest)

    repo = ApprovalRepository(db_runner._db)
    repo.resolve(approval_id, "approved", "test")

    log = db_runner.resume(run_log_id, approval_id)
    assert log is not None
    assert log.status == "completed"
    assert len(log.step_logs) == 3
    assert log.step_logs[0]["step_id"] == "c1"
    assert log.step_logs[0]["status"] == "ok"
    assert log.step_logs[1]["step_id"] == "a1"
    assert log.step_logs[1]["status"] == "approved"
    assert log.step_logs[2]["step_id"] == "t1"
    assert log.step_logs[2]["status"] == "ok"


def test_resume_rejected_returns_rejected(db_runner: SkillRunner) -> None:
    """Resume after approval is rejected returns rejected status."""
    manifest = _make_manifest("resume-rejected")
    run_log_id, approval_id = _run_and_get_ids(db_runner, manifest)

    repo = ApprovalRepository(db_runner._db)
    repo.resolve(approval_id, "rejected", "test")

    log = db_runner.resume(run_log_id, approval_id)
    assert log is not None
    assert log.status == "rejected"
    assert len(log.step_logs) == 2
    assert log.step_logs[1]["step_id"] == "a1"
    assert log.step_logs[1]["status"] == "rejected"


def test_resume_invalid_run_log_id(db_runner: SkillRunner) -> None:
    """Resume with non-existent run_log_id returns None."""
    result = db_runner.resume("nonexistent-run-log", "some-approval-id")
    assert result is None


def test_resume_non_pending_status(db_runner: SkillRunner) -> None:
    """Resume on a completed (non-pending_approval) run returns None."""
    manifest = SkillManifest(
        name="resume-not-pending",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="t1",
                name="simple",
                kind=StepKind.transform,
                input_mapping={"out": "hello"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "completed"

    cur = db_runner._db.connection.execute(
        "SELECT id FROM skill_run_logs WHERE trace_id = ?",
        (log.trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    run_log_id = str(row["id"])

    result = db_runner.resume(run_log_id, "some-approval-id")
    assert result is None
