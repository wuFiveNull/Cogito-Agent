from __future__ import annotations

import json

from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner


def test_approval_step_returns_pending_approval(db_runner: SkillRunner) -> None:
    """Run with approval step returns pending_approval, not completed."""
    manifest = SkillManifest(
        name="blocking-status",
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
                input_mapping={"out": "should-not-run"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"


def test_approval_step_blocks_remaining_steps(db_runner: SkillRunner) -> None:
    """Steps after approval step are not executed."""
    manifest = SkillManifest(
        name="blocking-steps",
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
                input_mapping={"out": "should-not-run"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert len(log.step_logs) == 2
    assert log.step_logs[0]["step_id"] == "c1"
    assert log.step_logs[0]["status"] == "ok"
    assert log.step_logs[1]["step_id"] == "a1"
    assert log.step_logs[1]["status"] == "pending_approval"


def test_approval_step_creates_pending_approval_record(db_runner: SkillRunner) -> None:
    """Approval step creates a pending approval record in the DB."""
    manifest = SkillManifest(
        name="blocking-record",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1",
                name="approve-me",
                kind=StepKind.approval,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"
    approval_id = log.step_logs[0]["output"]
    assert approval_id != ""

    cur = db_runner._db.connection.execute(
        "SELECT * FROM approval_records WHERE id = ?", (approval_id,)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["capability_name"] == "skill.approve-me"


def test_approval_step_logs_audit_entry(db_runner: SkillRunner) -> None:
    """Approval step logs an audit entry for approval_required."""
    manifest = SkillManifest(
        name="blocking-audit",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1",
                name="audit-me",
                kind=StepKind.approval,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"

    cur = db_runner._db.connection.execute(
        "SELECT * FROM audit_logs WHERE action = ? ORDER BY rowid DESC LIMIT 1",
        ("skill.approval_required",),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["decision"] == "require_approval"
    assert row["resource"] == "step:a1"


def test_approval_step_stores_resume_data(db_runner: SkillRunner) -> None:
    """Resume data is persisted in skill_run_logs after approval blocking."""
    manifest = SkillManifest(
        name="blocking-resume-data",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1",
                name="resume-data",
                kind=StepKind.approval,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"

    cur = db_runner._db.connection.execute(
        "SELECT resume_data_json FROM skill_run_logs WHERE trace_id = ?",
        (log.trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    resume_data = json.loads(row["resume_data_json"])
    assert resume_data["workspace_id"] == "ws-run"
    assert resume_data["manifest"]["name"] == "blocking-resume-data"
    assert isinstance(resume_data["step_index"], int)
    assert isinstance(resume_data["step_context"], dict)
    assert isinstance(resume_data["total_cost"], (int, float))
