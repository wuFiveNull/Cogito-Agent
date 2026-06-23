from __future__ import annotations

import json
import re
import time as _time
import uuid
from typing import Any

from cogito_agent.capability import CapabilityRegistry, _validate_json_schema
from cogito_agent.execution import (
    CapabilityExecutionRequest,
    GovernedCapabilityExecutor,
    default_guardians,
)
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.models import ModelAdapter
from cogito_agent.runs import RunRepository
from cogito_agent.shared import PolicyRequest, SpanKind
from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepKind,
)
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository
from cogito_agent.trace import Tracer
from cogito_agent.workspace.artifacts import ArtifactService


class SkillRunLog:
    def __init__(
        self,
        trace_id: str,
        skill_id: str,
        status: str,
        run_id: str = "",
    ):
        self.trace_id = trace_id
        self.skill_id = skill_id
        self.status = status
        self.run_id = run_id
        self.step_logs: list[dict[str, object]] = []
        self.outputs: dict[str, str] = {}
        self.artifact_ids: list[str] = []
        self.inbox_item_ids: list[str] = []
        self.proposal_ids: list[str] = []

    @property
    def output_types(self) -> list[str]:
        types: list[str] = []
        if self.artifact_ids:
            types.append("artifact")
        if self.inbox_item_ids:
            types.append("inbox")
        if self.proposal_ids:
            types.append("proposal")
        return types


class SkillRunner:
    def __init__(
        self,
        db: Database,
        capability_registry: CapabilityRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        model_adapter: ModelAdapter | None = None,
    ) -> None:
        self._db = db
        # Durable skill execution requires the run tables introduced by the
        # current migration set. Direct library callers historically invoked
        # only ``initialize()``, so make the runner boundary self-sufficient.
        self._db.migrate()
        self._cap_reg = capability_registry or CapabilityRegistry()
        self._policy = policy_engine or PolicyEngine()
        self._model_adapter = model_adapter
        self._tracer = Tracer(db)
        self._audit = AuditLogger(db)
        self._runs = RunRepository(db)
        self._worker_id = f"skill-runner:{uuid.uuid4()}"
        self._cap_executor = GovernedCapabilityExecutor(
            self._cap_reg,
            self._policy,
            approvals=ApprovalRepository(db),
            audit=self._audit,
            tracer=self._tracer,
            guardians=default_guardians(),
            artifact_writer=ArtifactService(db),
        )

    def run(
        self,
        manifest: SkillManifest,
        workspace_id: str,
        session_id: str = "",
        inputs: dict[str, str] | None = None,
        *,
        durable_run_id: str | None = None,
    ) -> SkillRunLog:
        # Registry and policy are replaceable extension points. Rebind the
        # executor at the run boundary so a newly loaded capability set cannot
        # bypass governance or leave the executor pointing at stale objects.
        self._cap_executor = GovernedCapabilityExecutor(
            self._cap_reg,
            self._policy,
            approvals=ApprovalRepository(self._db),
            audit=self._audit,
            tracer=self._tracer,
            guardians=default_guardians(),
            artifact_writer=ArtifactService(self._db),
        )
        if durable_run_id is None:
            durable = self._runs.create(
                run_type="skill",
                workspace_id=workspace_id,
                definition_id=manifest.name,
                max_attempts=2,
                input_data={"session_id": session_id, "inputs": inputs or {}},
            )
            durable_run_id = str(durable["id"])
        if not self._runs.claim(durable_run_id, worker_id=self._worker_id):
            raise RuntimeError(f"Could not claim skill run {durable_run_id}")

        trace = self._tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id=f"skill_{manifest.name}",
            session_id=session_id,
        )
        log = SkillRunLog(trace.id, manifest.name, "running", durable_run_id)
        self._runs.set_trace_id(durable_run_id, trace.id)
        audit = self._audit

        total_cost: float = 0.0
        executed_steps: list[SkillStep] = []
        step_context: dict[str, dict[str, str]] = {}

        try:
            self._preflight_all(manifest, workspace_id)
            self._check_semver(manifest)
        except Exception as exc:
            log.status = "failed"
            log.step_logs.append({"step_id": "preflight", "status": "error", "error": str(exc)})
            self._tracer.end_trace(trace, "failed")
            self._persist_run_log(log, workspace_id, manifest.name)
            self._finish_durable_run(log)
            raise

        for step_idx, step in enumerate(manifest.steps):
            if step.trace_required:
                span = self._tracer.create_span(trace.id, f"step_{step.id}", SpanKind.runtime)

            cfg = step.execution
            if cfg.max_budget_cost is not None and total_cost >= cfg.max_budget_cost:
                log.status = "failed"
                log.step_logs.append(
                    {
                        "step_id": step.id,
                        "status": "error",
                        "error": f"Budget exhausted ({total_cost}/{cfg.max_budget_cost})",
                    }
                )
                break

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
                    step,
                    workspace_id,
                    inputs or {},
                    step_context,
                    session_id=session_id,
                )
                executed_steps.append(step)
                norm = self._normalize_output(result)
                step_context[step.id] = {"_output": norm}
                if step.output_mapping:
                    for out_key, out_val in step.output_mapping.items():
                        step_context[step.id][out_key] = str(out_val)

                step_cost = self._estimate_step_cost(step)
                total_cost += step_cost

                step_status = "ok"
                step_output = norm[:500]
                if step.kind == StepKind.approval and isinstance(result, dict):
                    step_status = result.get("status", "ok")
                    step_output = str(result.get("approval_id", ""))
                    if step_status == "pending_approval":
                        log.status = "pending_approval"
                        log.step_logs.append(
                            {
                                "step_id": step.id,
                                "status": "pending_approval",
                                "output": step_output,
                                "artifacts": self._extract_artifacts(result),
                                "lineage": self._extract_lineage(result),
                            }
                        )
                        resume_data: dict[str, Any] = {
                            "durable_run_id": durable_run_id,
                            "manifest": manifest.model_dump(),
                            "step_index": step_idx,
                            "step_context": step_context,
                            "total_cost": total_cost,
                            "executed_steps": [s.model_dump() for s in executed_steps],
                            "workspace_id": workspace_id,
                            "session_id": session_id,
                            "inputs": inputs or {},
                        }
                        self._persist_run_log(log, workspace_id, manifest.name, resume_data)
                        self._record_run_outputs(log)
                        self._runs.pause_for_approval(
                            durable_run_id,
                            step_output,
                        )
                        if step.trace_required:
                            self._tracer.end_span(span)
                        self._tracer.end_trace(trace)
                        return log
                elif step.kind == StepKind.condition:
                    step_status = "ok"

                log.step_logs.append(
                    {
                        "step_id": step.id,
                        "status": step_status,
                        "output": step_output,
                        "artifacts": self._extract_artifacts(result),
                        "lineage": self._extract_lineage(result),
                    }
                )
            except Exception as e:
                log.step_logs.append(
                    {
                        "step_id": step.id,
                        "status": "error",
                        "error": str(e),
                    }
                )
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
        self._finish_durable_run(log)
        return log

    def resume(self, run_log_id: str, approval_id: str) -> SkillRunLog | None:
        cur = self._db.connection.execute(
            "SELECT * FROM skill_run_logs WHERE id = ?", (run_log_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        row_dict = dict(row)
        status = str(row_dict["status"])
        if status != "pending_approval":
            return None
        resume_json = row_dict.get("resume_data_json")
        if not resume_json:
            return None
        resume_data: dict[str, Any] = json.loads(str(resume_json))
        manifest = SkillManifest(**resume_data["manifest"])
        workspace_id = str(resume_data["workspace_id"])
        session_id = str(resume_data.get("session_id", ""))
        inputs: dict[str, str] = resume_data.get("inputs", {})
        step_context: dict[str, dict[str, str]] = resume_data.get("step_context", {})
        total_cost: float = float(resume_data.get("total_cost", 0.0))
        step_index: int = int(resume_data["step_index"])
        executed_steps: list[SkillStep] = [
            SkillStep(**s) for s in resume_data.get("executed_steps", [])
        ]

        from cogito_agent.storage.repositories import ApprovalRepository

        repo = ApprovalRepository(self._db)
        resolved = repo.get_by_id(approval_id)
        if resolved is None:
            return None
        decision = str(resolved.get("decision", ""))

        trace_id = str(row_dict["trace_id"])
        if not trace_id:
            return None
        durable_run_id = str(resume_data.get("durable_run_id", ""))
        log = SkillRunLog(trace_id, manifest.name, "running", durable_run_id)
        payload = json.loads(str(row_dict["step_logs_json"]))
        log.step_logs = payload.get("step_logs", []) if isinstance(payload, dict) else []
        log.outputs = payload.get("outputs", {}) if isinstance(payload, dict) else {}
        audit = AuditLogger(self._db)
        trace_obj = self._tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id=f"skill_{manifest.name}_resume",
            session_id=session_id,
        )
        log.trace_id = trace_obj.id
        approval_step = manifest.steps[step_index]

        if decision == "approved":
            if durable_run_id and not self._runs.resume_waiting(
                durable_run_id,
                worker_id=self._worker_id,
            ):
                return None
            for entry in log.step_logs:
                if entry.get("step_id") == approval_step.id:
                    entry["status"] = "approved"
                    break
            if approval_step.trace_required:
                span = self._tracer.create_span(
                    trace_obj.id, f"step_{approval_step.id}", SpanKind.runtime
                )
                self._tracer.end_span(span)
            audit.log(
                actor_id="skill",
                action="skill.resume.approved",
                resource=f"step:{approval_step.id}",
                workspace_id=workspace_id,
                trace_id=trace_obj.id,
                session_id=session_id or "",
                decision="allow",
                reason=f"Approval step '{approval_step.name}' approved, resuming",
            )

            remaining = manifest.steps[step_index + 1 :]
            for step in remaining:
                if step.trace_required:
                    span = self._tracer.create_span(
                        trace_obj.id, f"step_{step.id}", SpanKind.runtime
                    )

                cfg = step.execution
                if cfg.max_budget_cost is not None and total_cost >= cfg.max_budget_cost:
                    log.status = "failed"
                    log.step_logs.append(
                        {
                            "step_id": step.id,
                            "status": "error",
                            "error": f"Budget exhausted ({total_cost}/{cfg.max_budget_cost})",
                        }
                    )
                    break

                audit.log(
                    actor_id="skill",
                    action=f"skill.step.{step.kind.value}",
                    resource=f"step:{step.id}",
                    workspace_id=workspace_id,
                    trace_id=trace_obj.id,
                    session_id=session_id or "",
                    decision="allow",
                    reason=f"Resumed step {step.name} ({step.kind.value})",
                )

                try:
                    result = self._execute_step_with_controls(
                        step,
                        workspace_id,
                        inputs,
                        step_context,
                        session_id=session_id,
                    )
                    executed_steps.append(step)
                    norm = self._normalize_output(result)
                    step_context[step.id] = {"_output": norm}
                    if step.output_mapping:
                        for out_key, out_val in step.output_mapping.items():
                            step_context[step.id][out_key] = str(out_val)

                    step_cost = self._estimate_step_cost(step)
                    total_cost += step_cost

                    step_status = "ok"
                    step_output = norm[:500]
                    if step.kind == StepKind.approval and isinstance(result, dict):
                        step_status = result.get("status", "ok")
                        step_output = str(result.get("approval_id", ""))
                    elif step.kind == StepKind.condition:
                        step_status = "ok"

                    log.step_logs.append(
                        {
                            "step_id": step.id,
                            "status": step_status,
                            "output": step_output,
                            "artifacts": self._extract_artifacts(result),
                            "lineage": self._extract_lineage(result),
                        }
                    )
                except Exception as e:
                    log.step_logs.append(
                        {
                            "step_id": step.id,
                            "status": "error",
                            "error": str(e),
                        }
                    )
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
            self._tracer.end_trace(trace_obj)
            audit.log(
                actor_id="skill",
                action="skill.resume.completed",
                resource=f"run:{run_log_id}",
                workspace_id=workspace_id,
                trace_id=trace_obj.id,
                session_id=session_id or "",
                decision="allow",
                reason=f"Skill '{manifest.name}' resume completed with status {log.status}",
            )
            self._persist_run_log(log, workspace_id, manifest.name)
            self._finish_durable_run(log)
            return log

        else:
            for entry in log.step_logs:
                if entry.get("step_id") == approval_step.id:
                    entry["status"] = "rejected"
                    break
            log.status = "rejected"
            self._tracer.end_trace(trace_obj)
            audit.log(
                actor_id="skill",
                action="skill.resume.rejected",
                resource=f"step:{approval_step.id}",
                workspace_id=workspace_id,
                trace_id=trace_obj.id,
                session_id=session_id or "",
                decision="deny",
                reason=f"Approval step '{approval_step.name}' rejected",
            )
            self._persist_run_log(log, workspace_id, manifest.name)
            self._finish_durable_run(log)
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
            if (
                step.kind == StepKind.capability
                and step.uses_capability
                and self._cap_reg.get_manifest(step.uses_capability) is not None
            ):
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
                execution = self._cap_executor.execute(
                    CapabilityExecutionRequest(
                        capability_name=cap_name,
                        arguments={"workspace_id": workspace_id},
                        actor_id="skill",
                        source="interactive",
                        workspace_id=workspace_id,
                        operation="tool",
                    )
                )
                if not execution.succeeded:
                    self._audit.log(
                        actor_id="skill",
                        action="skill.rollback.failed",
                        resource=f"capability:{cap_name}",
                        workspace_id=workspace_id,
                        decision="deny",
                        reason=execution.reason,
                    )

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
        session_id: str = "",
    ) -> object:
        if step.kind == StepKind.transform:
            return self._apply_mapping(step, inputs, step_context)
        if step.kind == StepKind.capability and step.uses_capability:
            mapped: dict[str, object] = dict(self._apply_mapping(step, inputs, step_context))
            execution = self._cap_executor.execute(
                CapabilityExecutionRequest(
                    capability_name=step.uses_capability,
                    arguments=mapped,
                    actor_id="skill",
                    source="interactive",
                    workspace_id=workspace_id,
                    session_id=session_id,
                    operation="tool",
                )
            )
            if execution.status == "approval_required":
                raise PermissionError(
                    f"Capability '{step.uses_capability}' requires approval "
                    f"({execution.approval_id})"
                )
            if execution.status in {"denied", "not_found"}:
                raise PermissionError(
                    f"Capability '{step.uses_capability}' denied: {execution.reason}"
                )
            result = execution.tool_result
            if result is None:
                raise RuntimeError(f"Capability '{step.uses_capability}' not registered")
            return result
        if step.kind == StepKind.llm:
            return self._execute_llm_step(step, inputs, step_context)
        if step.kind == StepKind.condition:
            return self._evaluate_condition(step.condition_expression, inputs, step_context)
        if step.kind == StepKind.approval:
            return self._execute_approval_step(
                step,
                workspace_id,
                step_context,
                session_id=session_id,
            )
        return None

    def _execute_step_with_controls(
        self,
        step: SkillStep,
        workspace_id: str,
        inputs: dict[str, str],
        step_context: dict[str, dict[str, str]],
        session_id: str = "",
    ) -> object:
        cfg = step.execution

        for attempt in range(cfg.retry_count + 1):
            if attempt > 0:
                _time.sleep(cfg.retry_delay_seconds)

            start = _time.monotonic()
            try:
                result = self._execute_step(
                    step,
                    workspace_id,
                    inputs,
                    step_context,
                    session_id=session_id,
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
                        f"Output validation failed for step '{step.id}': {output_error}"
                    )

                return result
            except Exception as e:
                if attempt < cfg.retry_count:
                    continue
                if step.failure_policy == OnError.skip or step.on_error == OnError.skip:
                    return None
                if step.failure_policy == OnError.rollback or step.on_error == OnError.rollback:
                    raise RuntimeError(f"Step '{step.id}' failed with rollback: {e}") from e
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
        for match in re.finditer(r"\$(\w+)\.([\w.]+)", expression):
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
        session_id: str = "",
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
            session_id=session_id,
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
    def _validate_output(output: object, output_schema: dict[str, object]) -> str | None:
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
        messages: list[dict[str, object]] = [{"role": "user", "content": step.prompt}]
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

    @staticmethod
    def _estimate_step_cost(step: SkillStep) -> float:
        if step.kind == StepKind.llm:
            return 0.002
        if step.kind == StepKind.capability:
            return 0.001
        return 0.0

    def _persist_run_log(
        self,
        log: SkillRunLog,
        workspace_id: str,
        skill_name: str,
        resume_data: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "step_logs": log.step_logs,
            "outputs": log.outputs,
            "output_types": log.output_types,
            "artifact_ids": log.artifact_ids,
            "inbox_item_ids": log.inbox_item_ids,
            "proposal_ids": log.proposal_ids,
        }
        resume_json = json.dumps(resume_data) if resume_data else None
        self._db.connection.execute(
            "INSERT INTO skill_run_logs"
            " (id, workspace_id, skill_name, trace_id, status, step_logs_json, resume_data_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                workspace_id,
                skill_name,
                log.trace_id,
                log.status,
                json.dumps(payload),
                resume_json,
            ),
        )
        self._db.connection.commit()

    def _record_run_outputs(self, log: SkillRunLog) -> None:
        if not log.run_id:
            return
        for output_type, references in (
            ("artifact", log.artifact_ids),
            ("inbox", log.inbox_item_ids),
            ("proposal", log.proposal_ids),
        ):
            for reference_id in references:
                self._runs.add_output(log.run_id, output_type, reference_id)

    def _finish_durable_run(self, log: SkillRunLog) -> None:
        if not log.run_id:
            return
        self._record_run_outputs(log)
        status = "succeeded" if log.status == "completed" else "failed"
        if log.status == "rejected":
            status = "cancelled"
        error_message = ""
        if status == "failed":
            errors = [
                str(entry.get("error", ""))
                for entry in log.step_logs
                if entry.get("status") == "error"
            ]
            error_message = "; ".join(filter(None, errors))
        self._runs.finish(
            log.run_id,
            status=status,
            result_data={
                "skill_id": log.skill_id,
                "status": log.status,
                "output_types": log.output_types,
            },
            error_code="skill_failed" if status == "failed" else "",
            error_message=error_message,
        )

    def find_pending_approval_runs(self, limit: int = 20) -> list[dict[str, object]]:
        """Find skill run logs pending approval with resume data."""
        cur = self._db.connection.execute(
            "SELECT id FROM skill_run_logs"
            " WHERE resume_data_json IS NOT NULL AND status = 'pending_approval'"
            " ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    def get_skill_run_log(self, run_log_id: str) -> dict[str, object] | None:
        """Get a skill run log by id with resume and step data."""
        cur = self._db.connection.execute(
            "SELECT resume_data_json, step_logs_json, status FROM skill_run_logs"
            " WHERE id = ?",
            (run_log_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_skill_run_logs_by_trace(self, trace_id: str) -> list[dict[str, object]]:
        """Get all skill run logs for a given trace."""
        cur = self._db.connection.execute(
            "SELECT * FROM skill_run_logs WHERE trace_id = ? ORDER BY rowid",
            (trace_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            sj = r.get("step_logs_json")
            if isinstance(sj, str):
                try:
                    import json
                    r["steps"] = json.loads(sj)
                except (json.JSONDecodeError, TypeError):
                    r["steps"] = []
            r.pop("step_logs_json", None)
        return rows
