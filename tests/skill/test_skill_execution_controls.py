from __future__ import annotations

import time

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.shared import DecisionType
from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepExecutionConfig,
    StepKind,
)
from cogito_agent.skill import SkillRunner


def _make_cap_manifest(name: str = "test_cap"):
    from cogito_agent.shared import CapabilityManifest, CapabilityType, Permission, RiskLevel

    return CapabilityManifest(
        name=name,
        version="1.0",
        type=CapabilityType.tool,
        description="Test",
        input_schema={},
        output_schema={},
        permissions=[Permission(resource="*", operations=["execute"])],
        risk_level=RiskLevel.low,
        allowed_contexts=["interactive", "background"],
        approval_required=False,
        audit_required=True,
        idempotent=True,
    )


def test_per_step_timeout_fails_step(db_runner: SkillRunner) -> None:
    runner = db_runner
    registry = CapabilityRegistry()

    def _slow(text: str = "") -> ToolResult:
        time.sleep(0.3)
        return ToolResult(status="success", summary=text, data={"result": text})

    registry.register("slow", _make_cap_manifest("slow"), _slow)
    runner._cap_reg = registry
    runner._policy = PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.allow),
        ]
    )

    manifest = SkillManifest(
        name="timeout-test",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="t1",
                name="slow",
                kind=StepKind.capability,
                uses_capability="slow",
                input_mapping={"text": "$input.val"},
                execution=StepExecutionConfig(timeout_seconds=0.01),
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "failed"
    assert log.step_logs[0]["status"] == "error"
    assert "timed out" in str(log.step_logs[0].get("error", "")).lower()


def test_retry_succeeds_on_second_attempt(db_runner: SkillRunner) -> None:
    runner = db_runner
    registry = CapabilityRegistry()
    call_count: list[int] = [0]

    def _flaky(text: str = "") -> ToolResult:
        call_count[0] += 1
        if call_count[0] < 2:
            raise RuntimeError("First attempt failed")
        return ToolResult(status="success", summary=text, data={"result": text})

    registry.register("flaky", _make_cap_manifest("flaky"), _flaky)
    runner._cap_reg = registry
    runner._policy = PolicyEngine(
        rules=[
            PolicyRule("*", "*", "*", DecisionType.allow),
        ]
    )

    manifest = SkillManifest(
        name="retry-test",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="r1",
                name="flaky",
                kind=StepKind.capability,
                uses_capability="flaky",
                input_mapping={"text": "$input.val"},
                execution=StepExecutionConfig(retry_count=1, retry_delay_seconds=0.01),
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"
    assert log.step_logs[0]["status"] == "ok"
    assert call_count[0] == 2


def test_failure_policy_skip_continues_to_next_step(db_runner: SkillRunner) -> None:
    runner = db_runner
    manifest = SkillManifest(
        name="skip-continue",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="s1",
                name="failing",
                kind=StepKind.capability,
                uses_capability="nonexistent.tool",
                on_error=OnError.skip,
            ),
            SkillStep(
                id="s2",
                name="after",
                kind=StepKind.transform,
                input_mapping={"out": "$ok"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run")
    assert log.status == "completed"
    assert len(log.step_logs) == 2
    assert log.step_logs[1]["status"] == "ok"


def test_failure_policy_stop_breaks_execution(db_runner: SkillRunner) -> None:
    runner = db_runner
    manifest = SkillManifest(
        name="stop-break",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="b1",
                name="failing",
                kind=StepKind.capability,
                uses_capability="nonexistent.tool",
                on_error=OnError.stop,
            ),
            SkillStep(
                id="b2",
                name="after",
                kind=StepKind.transform,
                input_mapping={"out": "$ok"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run")
    assert log.status == "failed"
    assert len(log.step_logs) == 1
    assert log.step_logs[0]["status"] == "error"


def test_output_schema_validation_valid_passes(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="schema-pass",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="o1",
                name="valid",
                kind=StepKind.transform,
                input_mapping={"x": "$ok"},
                output_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "completed"
    assert log.step_logs[0]["status"] == "ok"


def test_output_schema_validation_invalid_fails(db_runner: SkillRunner) -> None:
    runner = db_runner
    manifest = SkillManifest(
        name="schema-fail",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="o1",
                name="invalid",
                kind=StepKind.transform,
                input_mapping={"x": "$ok"},
                output_schema={
                    "type": "object",
                    "properties": {"x": {"type": "number"}},
                },
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = runner.run(manifest, workspace_id="ws-run")
    assert log.status == "failed"
    assert log.step_logs[0]["status"] == "error"
    assert "validation" in str(log.step_logs[0].get("error", "")).lower()


def test_budget_enforcement_stops_execution(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="budget-test",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="b1",
                name="first",
                kind=StepKind.transform,
                input_mapping={"out": "$input.val"},
            ),
            SkillStep(
                id="b2",
                name="limited",
                kind=StepKind.transform,
                input_mapping={"out": "$input.val"},
                execution=StepExecutionConfig(max_budget_cost=0.0),
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "failed"
    assert len(log.step_logs) == 2
    assert log.step_logs[0]["status"] == "ok"
    assert log.step_logs[1]["status"] == "error"
    assert "Budget exhausted" in str(log.step_logs[1].get("error", ""))
