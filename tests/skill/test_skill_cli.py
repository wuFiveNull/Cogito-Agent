from __future__ import annotations

from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner


def test_cli_runner_run_basic(db_with_ws: SkillRunner) -> None:
    runner = db_with_ws
    manifest = SkillManifest(
        name="cli-test",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="s1",
                name="transform",
                kind=StepKind.transform,
                input_mapping={"out": "$val"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert len(log.step_logs) == 1
    assert log.step_logs[0]["status"] == "ok"


def test_cli_runner_handles_invalid_workspace(db_runner: SkillRunner) -> None:
    runner = db_runner
    manifest = SkillManifest(
        name="cli-bad-ws",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="s1",
                name="transform",
                kind=StepKind.transform,
                input_mapping={"out": "$ok"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="nonexistent")
    assert log.status == "completed"


def test_cli_runner_multi_step_logged(db_with_ws: SkillRunner) -> None:
    runner = db_with_ws
    manifest = SkillManifest(
        name="cli-multi",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="s1",
                name="first",
                kind=StepKind.transform,
                input_mapping={"out": "$val"},
            ),
            SkillStep(
                id="s2",
                name="second",
                kind=StepKind.transform,
                input_mapping={"out": "$step.s1._output"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run", inputs={"val": "chain"})
    assert log.status == "completed"
    assert len(log.step_logs) == 2
    for step_log in log.step_logs:
        assert step_log["status"] == "ok"
