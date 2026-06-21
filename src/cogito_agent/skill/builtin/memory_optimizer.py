from __future__ import annotations

from cogito_agent.shared.skill import SkillManifest, SkillRiskLevel
from cogito_agent.storage import Database

MEMORY_OPTIMIZER_MANIFEST = SkillManifest(
    name="memory_optimizer",
    version="1.0.0",
    description="Merge PENDING.md into MEMORY.md and update SELF.md using LLM.",
    inputs={},
    outputs={
        "pending_count": "Number of pending items merged",
        "memory_changed": "Whether MEMORY.md changed",
        "self_changed": "Whether SELF.md changed",
    },
    steps=[],
    risk_level=SkillRiskLevel.medium,
    owner="built-in",
)


def run_memory_optimizer(
    db: Database,
    workspace_id: str = "default",
    session_id: str = "",
    trace_id: str = "",
) -> dict[str, object]:
    from cogito_agent.application.runtime_factory import default_workspace_path
    from cogito_agent.cli.config_manager import build_model_adapter_from_config
    from cogito_agent.governance.audit import AuditLogger
    
    from cogito_agent.memory.optimizer import MemoryOptimizer
    from cogito_agent.shared import SpanKind
    from cogito_agent.trace import Tracer

    tracer = Tracer(db)
    audit = AuditLogger(db)

    if not trace_id:
        trace = tracer.create_trace(
            workspace_id=workspace_id,
            root_event_id="skill_memory_optimizer",
            session_id=session_id,
        )
        trace_id = trace.id

    span = tracer.create_span(trace_id, "memory_optimizer_run", SpanKind.autonomous)

    model = build_model_adapter_from_config()
    if model is None:
        tracer.end_span(span)
        tracer.end_trace(trace)
        return {
            "status": "skipped",
            "trace_id": trace_id,
            "reason": "No model adapter configured (set model.provider)",
        }

    workspace_path = default_workspace_path(workspace_id)

    opt = MemoryOptimizer(
        store=store,
        model_adapter=model,
        db=db,
        chunk_index=chunk_index,
        audit=audit,
        workspace_id=workspace_id,
    )

    result: dict[str, object] = {}
    try:
        raw = opt.run()
        result = {
            "pending_count": raw["pending_count"],
            "memory_changed": raw["memory_changed"],
            "self_changed": raw["self_changed"],
            "error": raw["error"],
        }
        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="memory_optimizer.run",
            input_summary=f"workspace={workspace_id}",
            output_summary=result,
            decision="allow",
        )
    except Exception as exc:
        tracer.log_tool_call(
            span_id=span.id,
            trace_id=trace_id,
            capability_name="memory_optimizer.run",
            input_summary=f"workspace={workspace_id}",
            output_summary={"error": str(exc)},
            decision="deny",
        )
        tracer.end_span(span)
        tracer.end_trace(trace)
        return {
            "status": "failed",
            "trace_id": trace_id,
            "error": str(exc),
        }

    audit.log(
        actor_id="skill",
        action="memory_optimizer.run",
        resource="memory",
        workspace_id=workspace_id,
        trace_id=trace_id,
        reason=f"pending={result.get('pending_count')}, memory_changed={result.get('memory_changed')}, self_changed={result.get('self_changed')}",
        redact_details=True,
    )

    tracer.end_span(span)
    tracer.end_trace(trace)

    return {
        "status": "completed",
        "trace_id": trace_id,
        **result,
    }
