from __future__ import annotations

from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepExecutionConfig,
    StepKind,
)
from cogito_agent.skill import SkillRunner
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository, WorkspaceRepository


def _init_db() -> Database:
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-e2e-v03", "v0.3-e2e")
    return db


def _make_manifest() -> SkillManifest:
    return SkillManifest(
        name="v03-core-flow",
        version="1.0.0",
        description="E2E test for approval lifecycle",
        risk_level=SkillRiskLevel.medium,
        steps=[
            SkillStep(
                id="s1",
                name="prepare",
                kind=StepKind.transform,
                input_mapping={"out": "started"},
                execution=StepExecutionConfig(timeout_seconds=10),
                on_error=OnError.stop,
            ),
            SkillStep(
                id="s2",
                name="require-approval",
                kind=StepKind.approval,
                input_mapping={},
                execution=StepExecutionConfig(timeout_seconds=10),
                on_error=OnError.stop,
            ),
            SkillStep(
                id="s3",
                name="finish",
                kind=StepKind.transform,
                input_mapping={"out": "completed-after-approval"},
                execution=StepExecutionConfig(timeout_seconds=10),
                on_error=OnError.stop,
            ),
        ],
    )


def test_v0_3_core_approval_lifecycle() -> None:
    """Full v0.3 approval lifecycle E2E: run -> approve -> resume -> complete."""
    db = _init_db()
    runner = SkillRunner(db)

    # Step 1: Run skill with approval step
    result = runner.run(_make_manifest(), "ws-e2e-v03", inputs={})
    assert result.status == "pending_approval", f"Expected pending_approval, got {result.status}"
    assert len(result.step_logs) == 2, f"Expected 2 step logs, got {len(result.step_logs)}"
    assert result.step_logs[0]["status"] == "ok"
    assert result.step_logs[1]["status"] == "pending_approval"

    # Step 2: Verify approval record created with pending status
    approval_id = str(result.step_logs[1]["output"])
    assert approval_id != ""

    repo = ApprovalRepository(db)
    approval = repo.get_by_id(approval_id)
    assert approval is not None
    assert approval["status"] == "pending"
    assert approval["workspace_id"] == "ws-e2e-v03"

    # Step 3: Find the skill_run_log id
    cur = db.connection.execute(
        "SELECT id FROM skill_run_logs WHERE status = 'pending_approval' AND workspace_id = ? ORDER BY rowid DESC LIMIT 1",
        ("ws-e2e-v03",),
    )
    row = cur.fetchone()
    assert row is not None
    run_log_id = str(row["id"])

    # Step 4: Approve via ApprovalRepository
    resolved = repo.resolve(approval_id, "approved", "e2e-test")
    assert resolved is not None
    assert resolved["status"] == "approved"
    assert resolved["decision"] == "approved"

    # Step 5: Resume skill run via SkillRunner
    resumed = runner.resume(run_log_id, approval_id)
    assert resumed is not None
    assert resumed.status == "completed", f"Expected completed, got {resumed.status}"

    # Step 6: Verify all three steps executed
    assert len(resumed.step_logs) == 3, f"Expected 3 step logs, got {len(resumed.step_logs)}"
    assert resumed.step_logs[0]["step_id"] == "s1"
    assert resumed.step_logs[0]["status"] == "ok"
    assert resumed.step_logs[1]["step_id"] == "s2"
    assert resumed.step_logs[1]["status"] == "approved"
    assert resumed.step_logs[2]["step_id"] == "s3"
    assert resumed.step_logs[2]["status"] == "ok"

    db.close()
