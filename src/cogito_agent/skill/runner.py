from __future__ import annotations

import json
import uuid

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.governance import PolicyEngine
from cogito_agent.shared import PolicyRequest, SpanKind
from cogito_agent.shared.skill import OnError, SkillManifest, SkillStep, StepKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


class SkillRunLog:
    def __init__(self, trace_id: str, skill_id: str, status: str):
        self.trace_id = trace_id
        self.skill_id = skill_id
        self.status = status
        self.step_logs: list[dict[str, object]] = []


class SkillRunner:
    def __init__(
        self,
        db: Database,
        capability_registry: CapabilityRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._db = db
        self._cap_reg = capability_registry or CapabilityRegistry()
        self._policy = policy_engine or PolicyEngine()
        self._tracer = Tracer(db)

    def run(
        self,
        manifest: SkillManifest,
        workspace_id: str,
        session_id: str = "",
        inputs: dict[str, str] | None = None,
    ) -> SkillRunLog:
        trace = self._tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id=f"skill_{manifest.name}",
            session_id=session_id,
        )
        log = SkillRunLog(trace.id, manifest.name, "running")

        for step in manifest.steps:
            span = self._tracer.create_span(
                trace.id, f"step_{step.id}", SpanKind.runtime
            )
            try:
                self._preflight(step, workspace_id)
                result = self._execute_step(step, workspace_id, inputs or {})
                log.step_logs.append({
                    "step_id": step.id,
                    "status": "ok",
                    "output": str(result)[:200],
                })
            except Exception as e:
                log.step_logs.append({
                    "step_id": step.id,
                    "status": "error",
                    "error": str(e),
                })
                if step.on_error == OnError.stop:
                    log.status = "failed"
                    self._tracer.end_span(span)
                    break
                if step.on_error == OnError.rollback:
                    log.status = "rolled_back"
                    self._tracer.end_span(span)
                    break
            self._tracer.end_span(span)

        if log.status == "running":
            log.status = "completed"
        self._tracer.end_trace(trace)
        self._persist_run_log(log, workspace_id, manifest.name)
        return log

    def _preflight(self, step: SkillStep, workspace_id: str) -> None:
        if step.kind == StepKind.capability and step.uses_capability:
            req = PolicyRequest(
                actor_id="skill",
                capability_name=step.uses_capability,
                resource="workspace_file",
                operation="read",
                context="interactive",
            )
            decision = self._policy.evaluate(req)
            if decision.decision.value == "deny":
                raise PermissionError(f"Policy denied step '{step.id}': {step.uses_capability}")

    def _execute_step(
        self, step: SkillStep, workspace_id: str, inputs: dict[str, str]
    ) -> object:
        if step.kind == StepKind.transform:
            return self._apply_mapping(step, inputs)
        if step.kind == StepKind.capability and step.uses_capability:
            mapped = self._apply_mapping(step, inputs)
            result = self._cap_reg.invoke(step.uses_capability, **mapped)
            return result
        if step.kind == StepKind.llm:
            return f"[llm step] {step.prompt}"
        return None

    def _apply_mapping(
        self, step: SkillStep, inputs: dict[str, str]
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in step.input_mapping.items():
            if v.startswith("$"):
                key = v[1:]
                result[k] = inputs.get(key, "")
            else:
                result[k] = v
        return result

    def _persist_run_log(
        self, log: SkillRunLog, workspace_id: str, skill_name: str
    ) -> None:
        self._db.connection.execute(
            "INSERT INTO skill_run_logs"
            " (id, workspace_id, skill_name, trace_id, status, step_logs_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                workspace_id,
                skill_name,
                log.trace_id,
                log.status,
                json.dumps(log.step_logs),
            ),
        )
        self._db.connection.commit()
