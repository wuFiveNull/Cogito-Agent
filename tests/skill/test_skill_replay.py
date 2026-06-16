from __future__ import annotations

import json

from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.skill import SkillRunner


def test_skill_run_creates_run_log_entry(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="replay-create",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="transform", kind=StepKind.transform,
                input_mapping={"out": "$ok"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "completed"

    cur = db_runner._db.connection.execute(
        "SELECT * FROM skill_run_logs WHERE trace_id = ?", (log.trace_id,)
    )
    row = cur.fetchone()
    assert row is not None
    assert row["skill_name"] == "replay-create"
    assert row["workspace_id"] == "ws-run"
    assert row["status"] == "completed"


def test_skill_run_log_contains_step_logs(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="replay-steps",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="first", kind=StepKind.transform,
                input_mapping={"out": "$val"},
            ),
            SkillStep(
                id="s2", name="second", kind=StepKind.transform,
                input_mapping={"out": "$step.s1._output"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"

    cur = db_runner._db.connection.execute(
        "SELECT step_logs_json FROM skill_run_logs WHERE trace_id = ?",
        (log.trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    payload = json.loads(row["step_logs_json"])
    assert "step_logs" in payload
    assert len(payload["step_logs"]) == 2
    assert payload["step_logs"][0]["step_id"] == "s1"
    assert payload["step_logs"][1]["step_id"] == "s2"


def test_skill_run_log_has_correct_status(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="replay-status",
        version="1.0.0",
        description="",
        inputs={},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="failing", kind=StepKind.capability,
                uses_capability="nonexistent.tool",
                on_error=OnError.stop,
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run")
    assert log.status == "failed"

    cur = db_runner._db.connection.execute(
        "SELECT status FROM skill_run_logs WHERE trace_id = ?",
        (log.trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["status"] == "failed"


def test_skill_run_log_has_step_logs_with_correct_statuses(db_runner: SkillRunner) -> None:
    manifest = SkillManifest(
        name="replay-step-statuses",
        version="1.0.0",
        description="",
        inputs={"val": "string"},
        outputs={},
        steps=[
            SkillStep(
                id="s1", name="first", kind=StepKind.transform,
                input_mapping={"out": "$val"},
            ),
            SkillStep(
                id="s2", name="second", kind=StepKind.transform,
                input_mapping={"out": "$step.s1._output"},
            ),
        ],
        permissions=[],
        risk_level=SkillRiskLevel.low,
    )
    log = db_runner.run(manifest, workspace_id="ws-run", inputs={"val": "hello"})
    assert log.status == "completed"

    cur = db_runner._db.connection.execute(
        "SELECT step_logs_json FROM skill_run_logs WHERE trace_id = ?",
        (log.trace_id,),
    )
    row = cur.fetchone()
    assert row is not None
    payload = json.loads(row["step_logs_json"])
    assert payload["step_logs"][0]["status"] == "ok"
    assert payload["step_logs"][1]["status"] == "ok"
