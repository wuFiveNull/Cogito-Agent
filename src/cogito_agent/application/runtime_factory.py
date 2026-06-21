from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cogito_agent.capability import CapabilityRegistry
from cogito_agent.governance import PolicyEngine
from cogito_agent.memory import (
    ConsolidationService,
    MemoryApplicationService,
)
from cogito_agent.models import ModelAdapter
from cogito_agent.retrieval import MemoryRetrievalPort
from cogito_agent.runtime import RuntimeKernel, TurnBudget
from cogito_agent.runtime.ports import RuntimeArtifactWriterPort
from cogito_agent.storage import Database


def default_workspace_path(workspace_id: str = "default") -> str:
    """Derive the workspace filesystem path for markdown memory files."""
    root = os.environ.get("COGITO_WORKSPACE_ROOT", "~/.cogito/workspace")
    return str(Path(os.path.expanduser(root)) / workspace_id)


def build_runtime_kernel(
    db: Database,
    *,
    budget: TurnBudget | None = None,
    model_adapter: ModelAdapter | None = None,
    capability_registry: CapabilityRegistry | None = None,
    policy_engine: PolicyEngine | None = None,
    artifact_writer: RuntimeArtifactWriterPort | None = None,
    max_tool_rounds: int = 3,
    workspace_path: str | None = None,
    **runtime_options: Any,
) -> RuntimeKernel:
    """Application composition root for the provider-neutral runtime kernel."""
    policy = policy_engine or PolicyEngine()
    services = db.create_runtime_services(
        capability_registry=capability_registry,
        policy_engine=policy,
        artifact_writer=artifact_writer,
    )
    memory_svc: MemoryApplicationService | None = None
    consolidation_svc: ConsolidationService | None = None
    retrieval_service: MemoryRetrievalPort | None = None
    if capability_registry is not None:
        # Wire the full retrieval pipeline
        from cogito_agent.retrieval.service import create_retrieval_service as _create_retrieval

        retrieval_service = _create_retrieval(db)

        memory_svc = MemoryApplicationService(
            db,
            retrieval_service=retrieval_service,
        )
        memory_svc.register_with_capability_registry(capability_registry)

        # Consolidation with Memorizer (Memory v2)
        if model_adapter:
            from cogito_agent.memory.memorizer import Memorizer

            memorizer = Memorizer(db)
            consolidation_svc = ConsolidationService(
                memorizer=memorizer,
                workspace_path=workspace_path or "",
                model_adapter=model_adapter,
            )
    kernel = RuntimeKernel(
        services,
        budget=budget,
        model_adapter=model_adapter,
        memory_retrieval_service=retrieval_service,
        max_tool_rounds=max_tool_rounds,
        **runtime_options,
    )
    if memory_svc is not None:
        kernel.set_memory_service(memory_svc)
    if consolidation_svc is not None:
        kernel.set_consolidation_service(consolidation_svc)
    return kernel
