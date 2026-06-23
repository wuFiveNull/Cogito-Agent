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
from cogito_agent.memory.ports import LLMExtractionPort
from cogito_agent.models import ModelAdapter
from cogito_agent.retrieval import MemoryRetrievalPort
from cogito_agent.runtime import RuntimeKernel, TurnBudget
from cogito_agent.runtime.extraction import LLMExtractionImpl
from cogito_agent.runtime.ports import RuntimeArtifactWriterPort
from cogito_agent.storage import Database

# ── Message queue / AgentLoop ─────────────────────────────────────────
from cogito_agent.queue import AgentLoop, MessageQueue


def default_workspace_path(workspace_id: str = "default") -> str:
    """Derive the workspace filesystem path for markdown memory files."""
    root = os.environ.get("COGITO_WORKSPACE_ROOT", "~/.cogito/workspace")
    return str(Path(os.path.expanduser(root)) / workspace_id)


def _init_self_md(workspace_path: str) -> None:
    """Write a default SELF.md if none exists."""
    from cogito_agent.memory.file_io import atomic_write_memory_file, read_memory_file

    existing = read_memory_file(workspace_path, "SELF.md")
    if existing:
        return

    content = (
        "# Self Model\n\n"
        "## 人格与形象\n"
        "- 我是一个有帮助的个人助手，运行在 Cogito-Agent 上\n"
        "- 我的目标是高效、准确地协助用户完成各类任务\n\n"
        "## 我对当前用户的理解\n"
        "- 我在逐步了解用户的过程中\n\n"
        "## 我们关系的定义\n"
        "- 我是用户的个人助手\n"
    )
    atomic_write_memory_file(workspace_path, "SELF.md", content)


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
    memory_retrieval_service: Any = None,
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
    retrieval_service: MemoryRetrievalPort | None = memory_retrieval_service
    if capability_registry is not None:
        # Wire the full retrieval pipeline (if not already provided)
        if retrieval_service is None:
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
            llm_extractor: LLMExtractionPort = LLMExtractionImpl(
                model=model_adapter,
            )
            consolidation_svc = ConsolidationService(
                memorizer=memorizer,
                workspace_path=workspace_path or "",
                llm_extractor=llm_extractor,
            )
    kernel = RuntimeKernel(
        services,
        budget=budget,
        model_adapter=model_adapter,
        memory_retrieval_service=retrieval_service,
        max_tool_rounds=max_tool_rounds,
        workspace_path=workspace_path or "",
        **runtime_options,
    )
    if memory_svc is not None:
        kernel.set_memory_service(memory_svc)
    if consolidation_svc is not None:
        kernel.set_consolidation_service(consolidation_svc)

    # Initialize SELF.md if it doesn't exist
    if workspace_path:
        _init_self_md(workspace_path)

    return kernel


def build_agent_loop(
    db: Database,
    *,
    kernel: RuntimeKernel | None = None,
    **kernel_options: Any,
) -> AgentLoop:
    """Build an AgentLoop around a (possibly shared) RuntimeKernel.

    If ``kernel`` is not provided, a new kernel is created via
    ``build_runtime_kernel()``.  The caller is responsible for starting
    and stopping the returned loop::

        loop = build_agent_loop(db)
        asyncio.create_task(loop.start())
        # ...
        await loop.stop()
    """
    if kernel is None:
        kernel = build_runtime_kernel(db, **kernel_options)

    queue = MessageQueue(db)
    return AgentLoop(kernel=kernel, queue=queue)
