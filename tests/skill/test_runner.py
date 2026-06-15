from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner

TRANSFORM_MANIFEST = SkillManifest(
    name="transform-test",
    version="1.0.0",
    description="A transform-only skill",
    inputs={"val": "string"},
    outputs={},
    steps=[
        SkillStep(
            id="s1", name="transform", kind=StepKind.transform,
            input_mapping={"out": "$val"},
        ),
    ],
    permissions=[],
    risk_level=SkillRiskLevel.low,
)


def test_run_transform_skill(db_with_ws: SkillRunner) -> None:
    runner = db_with_ws
    log = runner.run(TRANSFORM_MANIFEST, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert len(log.step_logs) == 1
    assert log.step_logs[0]["status"] == "ok"


def test_run_stop_on_error(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="error-skill",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="bad", name="bad-step", kind=StepKind.capability,
                uses_capability="nonexistent.tool",
                on_error=OnError.stop,
            ),
            SkillStep(
                id="s2", name="after", kind=StepKind.transform,
                input_mapping={"x": "$nonexistent"},
                on_error=OnError.stop,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    from cogito_agent.storage import Database
    from cogito_agent.storage.repositories import WorkspaceRepository

    db = Database(":memory:")
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-err", "test")
    runner = SkillRunner(db)
    log = runner.run(manifest, workspace_id="ws-err")
    assert log.status == "failed"
    assert len(log.step_logs) == 1


def test_run_skip_on_error(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="skip-skill",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="b1", name="skip-step", kind=StepKind.capability,
                uses_capability="nonexistent.tool",
                on_error=OnError.skip,
            ),
            SkillStep(
                id="b2", name="after-skip", kind=StepKind.transform,
                input_mapping={"x": "$val"},
                on_error=OnError.skip,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    from cogito_agent.storage import Database
    from cogito_agent.storage.repositories import WorkspaceRepository

    db = Database(":memory:")
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-skip", "test")
    runner = SkillRunner(db)
    log = runner.run(manifest, workspace_id="ws-skip")
    assert log.status == "completed"
    assert len(log.step_logs) == 2
