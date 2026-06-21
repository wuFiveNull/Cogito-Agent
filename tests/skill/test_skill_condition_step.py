from __future__ import annotations

from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner


def test_condition_empty_expression_returns_true(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="cond-empty",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="c1",
                name="check",
                kind=StepKind.condition,
                condition_expression="",
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "completed"
    assert len(log.step_logs) == 1
    assert log.step_logs[0]["status"] == "ok"


def test_condition_with_input_ref_resolves(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="cond-input",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="c1",
                name="check",
                kind=StepKind.condition,
                condition_expression="$input.val == 'hello'",
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert log.step_logs[0]["status"] == "ok"


def test_condition_with_step_output_ref_resolves(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="cond-step-ref",
        version="1.0.0",
        description="",
        inputs={"val": "hello"},
        outputs={},
        steps=[
            SkillStep(
                id="s1",
                name="transform",
                kind=StepKind.transform,
                input_mapping={"out": "$input.val"},
            ),
            SkillStep(
                id="c1",
                name="check",
                kind=StepKind.condition,
                condition_expression="$step.s1._output == 'hello'",
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert log.step_logs[1]["status"] == "ok"


def test_condition_with_contains_keyword(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="cond-contains",
        version="1.0.0",
        description="",
        inputs={"val": "hello world"},
        outputs={},
        steps=[
            SkillStep(
                id="c1",
                name="check",
                kind=StepKind.condition,
                condition_expression="$input.val contains 'world'",
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello world"})
    assert log.status == "completed"
    assert log.step_logs[0]["status"] == "ok"


def test_condition_false_does_not_break_run(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="cond-false",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="c1",
                name="check",
                kind=StepKind.condition,
                condition_expression="$input.val == 'world'",
            ),
            SkillStep(
                id="s1",
                name="after",
                kind=StepKind.transform,
                input_mapping={"out": "$input.val"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert len(log.step_logs) == 2
    assert log.step_logs[0]["status"] == "ok"
    assert log.step_logs[1]["status"] == "ok"


def test_condition_step_logged_with_status_ok(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="cond-status-ok",
        version="1.0.0",
        description="",
        inputs={"val": "true"},
        outputs={},
        steps=[
            SkillStep(
                id="c1",
                name="check",
                kind=StepKind.condition,
                condition_expression="$input.val == 'true'",
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "true"})
    assert log.status == "completed"
    assert log.step_logs[0]["status"] == "ok"
    assert "output" in log.step_logs[0]
