from cogito_agent.shared.skill import (
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillPool, WorkspaceSkill
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository

MANIFEST = SkillManifest(
    name="test-skill",
    version="1.0.0",
    description="A test skill",
    inputs={"text": "string"},
    outputs={},
    steps=[
        SkillStep(
            id="s1",
            name="step1",
            kind=StepKind.transform,
            input_mapping={"val": "$text"},
        ),
    ],
    permissions=[],
    risk_level=SkillRiskLevel.low,
)


def test_install_and_get(db: Database) -> None:
    pool = SkillPool(db)
    installed = pool.install(MANIFEST)
    assert installed["name"] == "test-skill"

    fetched = pool.get("test-skill")
    assert fetched is not None
    assert fetched["name"] == "test-skill"


def test_get_with_version(db: Database) -> None:
    pool = SkillPool(db)
    pool.install(MANIFEST)
    fetched = pool.get("test-skill", "1.0.0")
    assert fetched is not None


def test_get_nonexistent(db: Database) -> None:
    pool = SkillPool(db)
    assert pool.get("nonexistent") is None


def test_list_all(db: Database) -> None:
    pool = SkillPool(db)
    pool.install(MANIFEST)
    all_skills = pool.list_all()
    assert len(all_skills) >= 1


def test_copy_to_workspace(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-copy", "test")
    pool = SkillPool(db)
    installed = pool.install(MANIFEST)

    ws_skill = WorkspaceSkill(db)
    copied = ws_skill.copy_from_pool("ws-copy", installed["id"])
    assert copied is not None
    assert copied["workspace_id"] == "ws-copy"
    assert copied["name"] == "test-skill"
    assert copied["enabled"] == 1


def test_copy_nonexistent_pool(db: Database) -> None:
    ws_skill = WorkspaceSkill(db)
    result = ws_skill.copy_from_pool("ws-x", "nonexistent")
    assert result is None


def test_set_enabled(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-enable", "test")
    pool = SkillPool(db)
    installed = pool.install(MANIFEST)
    ws_skill = WorkspaceSkill(db)
    copied = ws_skill.copy_from_pool("ws-enable", installed["id"])

    ws_skill.set_enabled(copied["id"], False)
    updated = ws_skill.get(copied["id"])
    assert updated["enabled"] == 0
