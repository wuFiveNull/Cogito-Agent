from __future__ import annotations

import json
import re
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

        executed_steps: list[SkillStep] = []

        self._preflight_all(manifest, workspace_id)
        self._check_semver(manifest)

        for step in manifest.steps:
            span = self._tracer.create_span(
                trace.id, f"step_{step.id}", SpanKind.runtime
            )
            try:
                result = self._execute_step(step, workspace_id, inputs or {})
                executed_steps.append(step)
                log.step_logs.append({
                    "step_id": step.id,
                    "status": "ok",
                    "output": self._normalize_output(result)[:500],
                    "artifacts": self._extract_artifacts(result),
                    "lineage": self._extract_lineage(result),
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
                    self._execute_rollback(manifest, workspace_id, executed_steps)
                    self._tracer.end_span(span)
                    break
            self._tracer.end_span(span)

        if log.status == "running":
            log.status = "completed"
        self._tracer.end_trace(trace)
        self._persist_run_log(log, workspace_id, manifest.name)
        return log

    # ── M.4 Semver enforcement ──────────────────────────────────────────

    def _check_semver(self, manifest: SkillManifest) -> None:
        from cogito_agent.skill.storage import WorkspaceSkill

        ws_skill_repo = WorkspaceSkill(self._db)
        previous = ws_skill_repo.get_by_name(manifest.name)
        if previous is None:
            return
        prev_ver = self._parse_semver(str(previous["version"]))
        curr_ver = self._parse_semver(manifest.version)
        if prev_ver is None or curr_ver is None:
            return
        if curr_ver[0] > prev_ver[0]:
            raise PermissionError(
                f"Major version upgrade {previous['version']} -> {manifest.version}"
                f" for skill '{manifest.name}' requires re-approval"
            )

    @staticmethod
    def _parse_semver(version: str) -> tuple[int, ...] | None:
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None

    # ── M.2 Permission preflight ──────────────────────────────────────

    def _preflight_all(self, manifest: SkillManifest, workspace_id: str) -> None:
        for step in manifest.steps:
            if (step.kind == StepKind.capability
                    and step.uses_capability
                    and self._cap_reg.get_manifest(step.uses_capability) is not None):
                req = PolicyRequest(
                    actor_id="skill",
                    capability_name=step.uses_capability,
                    resource="workspace_file",
                    operation="read",
                    context="interactive",
                )
                decision = self._policy.evaluate(req)
                if decision.decision.value == "deny":
                    raise PermissionError(
                        f"Policy denied step '{step.id}': {step.uses_capability}"
                    )

    # ── M.1 Rollback compensation ─────────────────────────────────────

    def _execute_rollback(
        self,
        manifest: SkillManifest,
        workspace_id: str,
        executed_steps: list[SkillStep],
    ) -> None:
        for rollback_step in reversed(manifest.rollback):
            cap_name = rollback_step.get("uses_capability", "")
            if cap_name:
                self._cap_reg.invoke(cap_name, workspace_id=workspace_id)

    # ── M.3 Output normalization ─────────────────────────────────────

    @staticmethod
    def _normalize_output(result: object) -> str:
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, (bytes, bytearray)):
            return result.decode("utf-8", errors="replace")[:500]
        try:
            return str(result)[:500]
        except Exception:
            return "[unprintable output]"

    @staticmethod
    def _extract_artifacts(result: object) -> list[dict[str, object]]:
        if hasattr(result, "artifacts") and isinstance(result.artifacts, list):
            return result.artifacts
        return []

    @staticmethod
    def _extract_lineage(result: object) -> list[dict[str, object]]:
        if hasattr(result, "lineage") and isinstance(result.lineage, list):
            return result.lineage
        return []

    # ── Step execution ─────────────────────────────────────────────────

    def _execute_step(
        self, step: SkillStep, workspace_id: str, inputs: dict[str, str]
    ) -> object:
        if step.kind == StepKind.transform:
            return self._apply_mapping(step, inputs)
        if step.kind == StepKind.capability and step.uses_capability:
            mapped = self._apply_mapping(step, inputs)
            result = self._cap_reg.invoke(step.uses_capability, **mapped)
            if result is None:
                raise RuntimeError(
                    f"Capability '{step.uses_capability}' not registered"
                )
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
