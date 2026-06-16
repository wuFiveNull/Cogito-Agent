from __future__ import annotations

import pytest

from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


def test_rollback_on_error(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="rollback-skill",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="good", kind=StepKind.transform,
                input_mapping={"x": "$ok"},
                on_error=OnError.rollback,
            ),
            SkillStep(
                id="bad", name="fail", kind=StepKind.capability,
                uses_capability="nonexistent.tool",
                on_error=OnError.rollback,
            ),
        ],
        rollback=[
            {"uses_capability": "test.rollback"},
        ],
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "rolled_back"
    assert len(log.step_logs) == 2


def test_preflight_all_denies(db_runner: SkillRunner) -> None:
    from cogito_agent.capability import CapabilityRegistry
    from cogito_agent.capability.tools import READ_FILE_MANIFEST, _read_file
    from cogito_agent.governance.policy import DecisionType, PolicyEngine, PolicyRule

    policy = PolicyEngine(rules=[
        PolicyRule(
            actor="*", capability="*", operation="*", resource="*",
            context="interactive", decision=DecisionType.deny,
        ),
    ])
    cap_reg = CapabilityRegistry()
    cap_reg.register("local.file_read", READ_FILE_MANIFEST, _read_file)
    runner = SkillRunner(db_runner._db, capability_registry=cap_reg, policy_engine=policy)

    manifest = SkillManifest(
        name="preflight-test",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="blocked", kind=StepKind.capability,
                uses_capability="local.file_read",
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    with pytest.raises(PermissionError, match="Policy denied"):
        runner.run(manifest, workspace_id="ws-run")


def test_output_normalization_transform(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="norm-test",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="transform", kind=StepKind.transform,
                input_mapping={"out": "$val"},
            ),
        ],
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert "output" in log.step_logs[0]


def test_semver_rejects_major_upgrade() -> None:
    db = Database(":memory:")
    db.initialize()
    repo = WorkspaceRepository(db)
    repo.create("ws-semver", "test")

    from cogito_agent.skill.storage import WorkspaceSkill
    ws_skill = WorkspaceSkill(db)
    pool_manifest = SkillManifest(
        name="semver-test", version="1.0.0", description="v1",
        inputs={}, outputs={}, steps=[],
    )
    from cogito_agent.skill.storage import SkillPool
    pool = SkillPool(db)
    pool_row = pool.install(pool_manifest)
    ws_skill.copy_from_pool("ws-semver", pool_row["id"])

    runner = SkillRunner(db)
    new_manifest = SkillManifest(
        name="semver-test", version="2.0.0", description="v2 major",
        inputs={}, outputs={}, steps=[],
    )
    with pytest.raises(PermissionError, match="Major version"):
        runner.run(new_manifest, workspace_id="ws-semver")


def test_semver_allows_minor_upgrade() -> None:
    db = Database(":memory:")
    db.initialize()
    db.migrate()
    repo = WorkspaceRepository(db)
    repo.create("ws-semver2", "test")

    from cogito_agent.skill.storage import WorkspaceSkill
    ws_skill = WorkspaceSkill(db)
    from cogito_agent.skill.storage import SkillPool
    pool = SkillPool(db)
    pool_row = pool.install(SkillManifest(
        name="semver-minor", version="1.0.0", description="v1",
        inputs={}, outputs={}, steps=[],
    ))
    ws_skill.copy_from_pool("ws-semver2", pool_row["id"])

    runner = SkillRunner(db)
    new_manifest = SkillManifest(
        name="semver-minor", version="1.1.0", description="v1 minor",
        inputs={}, outputs={}, steps=[],
    )
    log = runner.run(new_manifest, workspace_id="ws-semver2")
    assert log.status == "completed"
