from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, Field

from cogito_agent.models import ModelRouter, ModelRouteRequest
from cogito_agent.models.messages import ContentPart, ImagePart

logger = logging.getLogger(__name__)


class TaskKind(StrEnum):
    vision_analysis = "vision_analysis"
    planning = "planning"
    coding = "coding"
    execution = "execution"
    summarization = "summarization"
    review = "review"
    chat = "chat"


class ExecutionStep(BaseModel):
    step_type: TaskKind
    role: str
    required_capabilities: set[str] = Field(default_factory=lambda: {"chat"})
    input_modalities: set[str] = Field(default_factory=lambda: {"text"})
    preferred_candidates: tuple[str, ...] = Field(default_factory=tuple)
    system_prompt: str = ""
    instruction: str = ""
    output_schema: dict[str, object] | None = None
    max_retries: int = 1

    @property
    def is_vision_step(self) -> bool:
        return self.step_type == TaskKind.vision_analysis

    @property
    def is_review_step(self) -> bool:
        return self.step_type == TaskKind.review


class OrchestrationPlan(BaseModel):
    steps: list[ExecutionStep] = Field(default_factory=list)
    has_vision: bool = False
    needs_review: bool = False
    raw_message: str = ""


def _is_coding_query(text: str) -> bool:
    keywords = [
        "write code",
        "implement",
        "fix bug",
        "refactor",
        "create file",
        "modify",
        "edit code",
        "add function",
        "write test",
        "debug",
        "pull request",
        "merge",
        "commit",
        "sort an array",
        "function",
    ]
    lower = text.lower()
    for kw in keywords:
        if kw in lower:
            return True
    return False


def _is_high_risk(text: str) -> bool:
    risk_keywords = [
        "delete",
        "remove file",
        "drop table",
        "rm -rf",
        "format",
        "overwrite",
        "shutdown",
        "restart",
        "sudo",
        "chmod",
        "production",
        "critical",
        "important config",
        "delete all",
    ]
    lower = text.lower()
    for kw in risk_keywords:
        if kw in lower:
            return True
    return False


def _estimate_input_tokens(text: str) -> int:
    try:
        from cogito_agent.models import token_count

        return token_count(text)
    except Exception:
        return max(1, len(text) // 4)


class TaskOrchestrator:
    """Deterministic orchestrator that builds execution plans.

    The orchestrator uses rules (not LLM) to decompose a request into
    execution steps. ModelRouter is then used to select concrete models
    for each step.

    This class does NOT call models directly — it only produces plans.
    """

    def __init__(
        self,
        router: ModelRouter,
        max_context_tokens: int = 24000,
    ) -> None:
        self._router = router
        self._max_context_tokens = max_context_tokens

    def plan(
        self,
        message: str = "",
        content: list[ContentPart] | None = None,
        has_tools: bool = False,
        actor_role: str = "user",
    ) -> OrchestrationPlan:
        """Build an execution plan based on message content and context.

        Args:
            message: The plain text message (if any).
            content: Structured content parts (images, files, text).
            has_tools: Whether tools are available.
            actor_role: The role of the requesting actor.

        Returns:
            An OrchestrationPlan with ordered execution steps.
        """
        parts = list(content or [])
        has_image = any(isinstance(p, ImagePart) for p in parts)
        has_code = _is_coding_query(message) if message else False
        is_high_risk = _is_high_risk(message) if message else False
        estimated_tokens = _estimate_input_tokens(message) if message else 0
        near_limit = estimated_tokens > self._max_context_tokens * 0.8

        steps: list[ExecutionStep] = []
        needs_review = is_high_risk
        plan = OrchestrationPlan(
            has_vision=has_image,
            needs_review=needs_review,
            raw_message=message,
        )

        # Rule 1: If there are images, add a vision analysis step
        if has_image:
            steps.append(
                ExecutionStep(
                    step_type=TaskKind.vision_analysis,
                    role="vision_worker",
                    required_capabilities={"chat", "vision", "json"},
                    input_modalities={"text", "image"},
                    preferred_candidates=tuple(),
                    system_prompt="",
                    output_schema={
                        "summary": "string",
                        "ocr_text": ["string"],
                        "objects": ["string"],
                        "ui_elements": [{"type": "object"}],
                    },
                )
            )

        # Rule 2: If near context limit, add summarization
        if near_limit:
            steps.append(
                ExecutionStep(
                    step_type=TaskKind.summarization,
                    role="summarizer",
                    required_capabilities={"chat", "reasoning"},
                    input_modalities={"text"},
                    preferred_candidates=tuple(),
                )
            )

        # Rule 3: Code queries go to coder
        if has_code:
            steps.append(
                ExecutionStep(
                    step_type=TaskKind.coding,
                    role="coder",
                    required_capabilities={"chat", "reasoning", "code"},
                    input_modalities={"text"},
                    preferred_candidates=tuple(),
                )
            )
        # Rule 4: Tool calls go to executor
        elif has_tools:
            steps.append(
                ExecutionStep(
                    step_type=TaskKind.execution,
                    role="executor",
                    required_capabilities={"chat", "tools"},
                    input_modalities={"text"},
                    preferred_candidates=tuple(),
                )
            )
        # Rule 5: Default to planning/chat
        else:
            steps.append(
                ExecutionStep(
                    step_type=TaskKind.planning if message else TaskKind.chat,
                    role="planner" if message else "chat",
                    required_capabilities={"chat"},
                    input_modalities={"text"},
                    preferred_candidates=tuple(),
                )
            )

        # Rule 6: High-risk operations need review (code or otherwise)
        if is_high_risk:
            steps.append(
                ExecutionStep(
                    step_type=TaskKind.review,
                    role="reviewer",
                    required_capabilities={"chat", "reasoning"},
                    input_modalities={"text"},
                    preferred_candidates=tuple(),
                    system_prompt=(
                        "You are a reviewer. Review the proposed operation "
                        "for correctness, security, and potential side effects. "
                        "If you find issues, explain them clearly."
                    ),
                )
            )

        plan.steps = steps
        return plan

    def create_router_request(
        self,
        step: ExecutionStep,
        estimated_tokens: int = 0,
    ) -> ModelRouteRequest:
        """Create a ModelRouteRequest from an ExecutionStep."""
        return ModelRouteRequest(
            required_capabilities=step.required_capabilities,
            required_input_modalities=step.input_modalities,
            role=step.role,
            task_kind=step.step_type.value,
            estimated_input_tokens=estimated_tokens or 0,
            preferred_candidates=step.preferred_candidates,
        )

    def select_model_for_step(
        self,
        step: ExecutionStep,
        estimated_tokens: int = 0,
    ) -> str | None:
        """Route a step to a model and return the candidate id, or None."""
        req = self.create_router_request(step, estimated_tokens)
        decision = self._router.route(req)
        if decision.selected is None:
            return None
        return decision.selected.id
