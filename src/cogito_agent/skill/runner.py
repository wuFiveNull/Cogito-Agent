from __future__ import annotations

import json
import re
import time as _time
import uuid

from cogito_agent.capability import CapabilityRegistry, _validate_json_schema
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.models import ModelAdapter
from cogito_agent.shared import PolicyRequest, SpanKind
from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer


class SkillRunLog:
    def __init__(self, trace_id: str, skill_id: str, status: str):
        self.trace_id = trace_id
        self.skill_id = skill_id
        self.status = status
        self.step_logs: list[dict[str, object]] = []
        self.outputs: dict[str, str] = {}


class SkillRunner:
    def __init__(
        self,
        db: Database,
        capability_registry: CapabilityRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        model_adapter: ModelAdapter | None = None,
    ) -> None:
        self._db = db
        self._cap_reg = capability_registry or CapabilityRegistry()
        self._policy = policy_engine or PolicyEngine()
        self._model_adapter = model_adapter
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
        audit = AuditLogger(self._db)

        executed_steps: list[SkillStep] = []
        step_context: dict[str, dict[str, str]] = {}

        self._preflight_all(manifest, workspace_id)
        self._check_semver(manifest)

        for step in manifest.steps:
            if step.trace_required:
                span = self._tracer.create_span(
                    trace.id, f"step_{step.id}", SpanKind.runtime
                )

            # Governance: audit each step execution
            decision = "allow"
            reason = f"Executing step {step.name} ({step.kind.value})"
            if manifest.risk_level in (SkillRiskLevel.high, SkillRiskLevel.critical):
                reason = f"High-risk step {step.name}"
            audit.log(
                actor_id="skill",
                action=f"skill.step.{step.kind.value}",
                resource=f"step:{step.id}",
                workspace_id=workspace_id,
                trace_id=trace.id,
                session_id=session_id or "",
                decision=decision,
                reason=reason,
            )

            try:
                result = self._execute_step_with_controls(
                    step, workspace_id, inputs or {}, step_context
                )
                executed_steps.append(step)
                norm = self._normalize_output(result)
                step_context[step.id] = {"_output": norm}
                if step.output_mapping:
                    for out_key, out_val in step.output_mapping.items():
                        step_context[step.id][out_key] = str(out_val)

                step_status = "ok"
                step_output = norm[:500]
                if step.kind == StepKind.approval and isinstance(result, dict):
                    step_status = result.get("status", "ok")
                    step_output = str(result.get("approval_id", ""))
                elif step.kind == StepKind.condition:
                    step_status = "ok"

                log.step_logs.append({
                    "step_id": step.id,
                    "status": step_status,
                    "output": step_output,
                    "artifacts": self._extract_artifacts(result),
                    "lineage": self._extract_lineage(result),
                })
            except Exception as e:
                log.step_logs.append({
                    "step_id": step.id,
                    "status": "error",
                    "error": str(e),
                })
                failure = step.on_error
                if failure == OnError.stop:
                    log.status = "failed"
                    if step.trace_required:
                        self._tracer.end_span(span)
                    break
                if failure == OnError.rollback:
                    log.status = "rolled_back"
                    self._execute_rollback(manifest, workspace_id, executed_steps)
                    if step.trace_required:
                        self._tracer.end_span(span)
                    break
            if step.trace_required:
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
        self,
        step: SkillStep,
        workspace_id: str,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
    ) -> object:
        if step.kind == StepKind.transform:
            return self._apply_mapping(step, inputs, step_context)
        if step.kind == StepKind.capability and step.uses_capability:
            mapped = self._apply_mapping(step, inputs, step_context)
            result = self._cap_reg.invoke(step.uses_capability, **mapped)
            if result is None:
                raise RuntimeError(
                    f"Capability '{step.uses_capability}' not registered"
                )
            return result
        if step.kind == StepKind.llm:
            return self._execute_llm_step(step, inputs, step_context)
        if step.kind == StepKind.condition:
            return self._evaluate_condition(
                step.condition_expression, inputs, step_context
            )
        if step.kind == StepKind.approval:
            return self._execute_approval_step(step, workspace_id, step_context)
        return None

    def _execute_step_with_controls(
        self,
        step: SkillStep,
        workspace_id: str,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
    ) -> object:
        cfg = step.execution

        for attempt in range(cfg.retry_count + 1):
            if attempt > 0:
                _time.sleep(cfg.retry_delay_seconds)

            start = _time.monotonic()
            try:
                result = self._execute_step(
                    step, workspace_id, inputs, step_context
                )
                elapsed = _time.monotonic() - start
                if cfg.timeout_seconds > 0 and elapsed > cfg.timeout_seconds:
                    raise TimeoutError(
                        f"Step '{step.id}' timed out after {elapsed:.1f}s"
                        f" (limit {cfg.timeout_seconds}s)"
                    )

                output_error = self._validate_output(result, step.output_schema)
                if output_error:
                    raise ValueError(
                        "Output validation failed for step"
                        f" '{step.id}': {output_error}"
                    )

                return result
            except Exception as e:
                if attempt < cfg.retry_count:
                    continue
                if step.failure_policy == OnError.skip or step.on_error == OnError.skip:
                    return None
                if step.failure_policy == OnError.rollback or step.on_error == OnError.rollback:
                    raise RuntimeError(
                        f"Step '{step.id}' failed with rollback: {e}"
                    ) from e
                raise

        raise RuntimeError("Unreachable")

    def _evaluate_condition(
        self,
        expression: str,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
    ) -> bool:
        if not expression:
            return True
        resolved = expression
        for match in re.finditer(r'\$(\w+)\.([\w.]+)', expression):
            prefix = match.group(1)
            path = match.group(2)
            parts = path.split(".")
            if prefix == "input":
                val: object = inputs.get(parts[0], "")
            elif prefix == "step":
                ctx = step_context.get(parts[0], {})
                val = ctx.get(parts[1] if len(parts) > 1 else "_output", "")
            else:
                val = ""
            if isinstance(val, str):
                val = f'"{val}"'
            resolved = resolved.replace(match.group(0), str(val))
        resolved = resolved.replace(" contains ", " in ")
        try:
            safe_globals: dict[str, object] = {"__builtins__": {}}
            return bool(eval(resolved, safe_globals, {}))  # noqa: S307
        except Exception:
            return False

    def _execute_approval_step(
        self,
        step: SkillStep,
        workspace_id: str,
        step_context: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        from cogito_agent.storage.repositories import ApprovalRepository

        repo = ApprovalRepository(self._db)
        audit = AuditLogger(self._db)
        approval = repo.create(
            workspace_id=workspace_id,
            actor_id="skill",
            capability_name=f"skill.{step.name}",
            operation="execute",
            reason=f"Approval step: {step.name}",
            session_id=step_context.get("_session_id", ""),
        )
        audit.log(
            actor_id="skill",
            action="skill.approval_required",
            resource=f"step:{step.id}",
            workspace_id=workspace_id,
            decision="require_approval",
            reason=f"Approval step '{step.name}' requires user approval",
        )
        return {"status": "pending_approval", "approval_id": str(approval.get("id", ""))}

    @staticmethod
    def _validate_output(
        output: object, output_schema: dict[str, object]
    ) -> str | None:
        if not output_schema:
            return None
        if isinstance(output, str):
            output_dict: dict[str, object] = {"output": output}
        elif isinstance(output, dict):
            output_dict = output
        else:
            output_dict = {"result": str(output)}
        return _validate_json_schema(output_schema, output_dict)

    def _execute_llm_step(
        self,
        step: SkillStep,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
    ) -> str:
        if self._model_adapter is None:
            prompt = step.prompt or ""
            mapped = self._apply_mapping(step, inputs, step_context)
            if mapped:
                prompt = prompt.format(**mapped)
            return f"[llm stub] {prompt[:200]}"
        messages: list[dict[str, str]] = [{"role": "user", "content": step.prompt}]
        response = self._model_adapter.chat(messages)
        return response.content or ""

    def _resolve_ref(
        self,
        ref: str,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
    ) -> str:
        parts = ref.split(".")
        if parts[0] == "input" and len(parts) == 2:
            return inputs.get(parts[1], "")
        if parts[0] == "step" and len(parts) >= 2:
            ctx = step_context.get(parts[1], {})
            if len(parts) == 2:
                return ctx.get("_output", "")
            return ctx.get(parts[2], "")
        return inputs.get(ref, "")

    def _apply_mapping(
        self,
        step: SkillStep,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for k, v in step.input_mapping.items():
            if v.startswith("$"):
                result[k] = self._resolve_ref(v[1:], inputs, step_context)
            else:
                result[k] = v
        return result

    def _persist_run_log(
        self, log: SkillRunLog, workspace_id: str, skill_name: str
    ) -> None:
        payload = {
            "step_logs": log.step_logs,
            "outputs": log.outputs,
        }
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
                json.dumps(payload),
            ),
        )
        self._db.connection.commit()
