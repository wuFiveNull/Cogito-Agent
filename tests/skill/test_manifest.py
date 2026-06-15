from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)

EXAMPLE_MANIFEST = SkillManifest(
    name="example-summarize",
    version="1.0.0",
    description="Summarize a given text",
    inputs={"text": "string"},
    outputs={"summary": "string"},
    steps=[
        SkillStep(
            id="step-1",
            name="transform-input",
            kind=StepKind.transform,
            input_mapping={"input_text": "$text"},
            output_mapping={},
            on_error=OnError.stop,
        ),
        SkillStep(
            id="step-2",
            name="read-file",
            kind=StepKind.capability,
            uses_capability="local.file_read",
            input_mapping={"path": "$text"},
            on_error=OnError.stop,
        ),
    ],
    permissions=[{"resource": "workspace_file", "operations": ["read"]}],
    risk_level=SkillRiskLevel.medium,
)


def test_manifest_valid() -> None:
    assert EXAMPLE_MANIFEST.name == "example-summarize"
    assert len(EXAMPLE_MANIFEST.steps) == 2
    assert EXAMPLE_MANIFEST.steps[0].kind == StepKind.transform


def test_manifest_serialization() -> None:
    json_str = EXAMPLE_MANIFEST.model_dump_json()
    restored = SkillManifest.model_validate_json(json_str)
    assert restored.name == EXAMPLE_MANIFEST.name
    assert restored.steps[0].id == "step-1"


def test_step_kinds() -> None:
    assert StepKind.capability.value == "capability"
    assert StepKind.transform.value == "transform"
    assert StepKind.llm.value == "llm"


def test_on_error_values() -> None:
    assert OnError.stop.value == "stop"
    assert OnError.skip.value == "skip"
    assert OnError.rollback.value == "rollback"
