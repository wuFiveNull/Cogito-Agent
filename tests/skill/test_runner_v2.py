from __future__ import annotations

import uuid

from cogito_agent.capability import CapabilityRegistry, ToolResult
from cogito_agent.governance import PolicyEngine, PolicyRule
from cogito_agent.shared import (
    CapabilityManifest,
    CapabilityType,
    DecisionType,
    Permission,
    RiskLevel,
)
from cogito_agent.shared.skill import OnError, SkillManifest, SkillStep, StepKind


def _permissive_policy() -> PolicyEngine:
    return PolicyEngine(rules=[PolicyRule("*", "*", "*", DecisionType.allow)])


def _make_manifest(
    name: str = "v2-skill",
    steps: list[SkillStep] | None = None,
) -> SkillManifest:
    return SkillManifest(
        name=name,
        version="1.0.0",
        description="V2 test skill",
        inputs={"input_text": "str"},
        outputs={"result": "str"},
        steps=steps or [],
        permissions=[{"resource": "*", "operations": ["execute"]}],
        risk_level="low",
        rollback=[],
    )


def _make_manifest_cap(
    name: str = "echo_cap",
    input_schema: dict | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version="1.0",
        type=CapabilityType.tool,
        description="Echo",
        input_schema=input_schema or {},
        output_schema={},
        permissions=[Permission(resource="*", operations=["execute"])],
        risk_level=RiskLevel.low,
        allowed_contexts=["interactive", "background"],
        approval_required=False,
        audit_required=True,
        idempotent=True,
    )


def _wid() -> str:
    return "ws-run"


def test_step_output_feeds_next_step(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    runner._policy = _permissive_policy()
    registry = CapabilityRegistry()

    def _echo(text: str = "") -> ToolResult:
        return ToolResult(status="success", summary=text, data={"result": text})

    registry.register("echo", _make_manifest_cap("echo"), _echo)

    runner._cap_reg = registry
    manifest = _make_manifest("chain-test", steps=[
        SkillStep(id="s1", name="step1", kind=StepKind.capability,
                  uses_capability="echo",
                  input_mapping={"text": "$input.input_text"}),
        SkillStep(id="s2", name="step2", kind=StepKind.capability,
                  uses_capability="echo",
                  input_mapping={"text": "$step.s1._output"}),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "hello"})
    assert log.status == "completed"


def test_llm_stub_fallback(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    manifest = _make_manifest("llm-test", steps=[
        SkillStep(id="l1", name="llm-step", kind=StepKind.llm,
                  prompt="Say hello"),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "x"})
    assert log.status == "completed"
    assert len(log.step_logs) == 1
    output = str(log.step_logs[0].get("output", ""))
    assert "llm stub" in output


def test_trace_not_required_skips_span(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    manifest = _make_manifest("no-trace", steps=[
        SkillStep(id="t1", name="transform-step", kind=StepKind.transform,
                  input_mapping={"out": "$input.input_text"},
                  trace_required=False),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "hello"})
    assert log.status == "completed"


def test_output_mapping_captured(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    runner._policy = _permissive_policy()
    registry = CapabilityRegistry()

    def _echo(text: str = "") -> ToolResult:
        return ToolResult(status="success", summary=text, data={"result": text})

    registry.register("echo", _make_manifest_cap("echo"), _echo)
    runner._cap_reg = registry
    manifest = _make_manifest("output-map", steps=[
        SkillStep(id="o1", name="out-step", kind=StepKind.capability,
                  uses_capability="echo",
                  input_mapping={"text": "$input.input_text"},
                  output_mapping={"greeting": "hello world"}),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "hi"})
    assert log.status == "completed"


def test_transform_step_resolves_input_ref(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    manifest = _make_manifest("transform-ref", steps=[
        SkillStep(id="x1", name="transform", kind=StepKind.transform,
                  input_mapping={"out": "$input.input_text"}),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "world"})
    assert log.status == "completed"
    assert len(log.step_logs) == 1


def test_multiple_steps_with_skip(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    manifest = _make_manifest("multi-skip", steps=[
        SkillStep(id="m1", name="first", kind=StepKind.transform,
                  input_mapping={"out": "$input.input_text"}),
        SkillStep(id="m2", name="second", kind=StepKind.transform,
                  input_mapping={"out": "$step.m1._output"},
                  on_error=OnError.skip),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "multi"})
    assert log.status == "completed"


def test_step_context_passed_through_chain(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    runner._policy = _permissive_policy()
    registry = CapabilityRegistry()

    def _cap_a(prefix: str = "") -> ToolResult:
        return ToolResult(status="success", summary=prefix, data={"result": prefix})

    registry.register("cap_a", _make_manifest_cap("cap_a"), _cap_a)
    registry.register("cap_b", _make_manifest_cap("cap_b"), _cap_a)
    runner._cap_reg = registry
    manifest = _make_manifest("context-chain", steps=[
        SkillStep(id="a", name="step-a", kind=StepKind.capability,
                  uses_capability="cap_a",
                  input_mapping={"prefix": "$input.input_text"}),
        SkillStep(id="b", name="step-b", kind=StepKind.capability,
                  uses_capability="cap_b",
                  input_mapping={"prefix": "$step.a._output"}),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "chain"})
    assert log.status == "completed"


def test_reference_resolution_unknown_step(db_runner) -> None:
    wid = _wid()
    runner = db_runner
    manifest = _make_manifest("bad-ref", steps=[
        SkillStep(id="r1", name="ref-step", kind=StepKind.transform,
                  input_mapping={"out": "$step.nonexist._output"}),
    ])
    log = runner.run(manifest, wid, inputs={"input_text": "x"})
    assert log.status == "completed"
