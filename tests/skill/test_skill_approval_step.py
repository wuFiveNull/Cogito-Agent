from __future__ import annotations

from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner


def test_approval_step_creates_pending_approval_record(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="approval-create",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1", name="approve-me", kind=StepKind.approval,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"
    assert len(log.step_logs) == 1

    cur = db_runner._db.connection.execute(
        "SELECT * FROM approval_records WHERE workspace_id = ?",
        ("ws-run",),
    )
    rows = cur.fetchall()
    assert len(rows) >= 1
    latest = rows[-1]
    assert latest["status"] == "pending"
    assert latest["capability_name"] == "skill.approve-me"


def test_approval_step_returns_pending_approval_status(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="approval-status",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1", name="approve-me", kind=StepKind.approval,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "pending_approval"
    assert log.step_logs[0]["status"] == "pending_approval"
    assert log.step_logs[0]["output"] != ""


def test_approval_step_logs_audit_entry(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="approval-audit",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1", name="approve-me", kind=StepKind.approval,
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


def test_approval_step_records_id_in_output(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="approval-id",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="a1", name="approve-me", kind=StepKind.approval,
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
        "SELECT id FROM approval_records WHERE id = ?", (approval_id,)
    )
    row = cur.fetchone()
    assert row is not None
