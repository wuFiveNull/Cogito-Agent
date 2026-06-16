from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class TurnState(StrEnum):
    received = "received"
    loading_session = "loading_session"
    building_context = "building_context"
    model_calling = "model_calling"
    planning_tool = "planning_tool"
    policy_checking = "policy_checking"
    waiting_approval = "waiting_approval"
    executing_capability = "executing_capability"
    updating_context = "updating_context"
    composing_result = "composing_result"
    extracting_memory = "extracting_memory"
    retrying = "retrying"
    interrupted = "interrupted"
    resuming = "resuming"
    completed = "completed"
    failed = "failed"
    denied = "denied"
    cancelled = "cancelled"
    budget_exceeded = "budget_exceeded"


class TurnBudget(BaseModel):
    max_steps: int = 12
    max_model_calls: int = 4
    max_tool_calls: int = 5
    max_context_tokens: int = 24000
    max_output_tokens: int = 4000
    max_cost_usd: float | None = None
    deadline_at: datetime | None = None


_TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.received: {
        TurnState.loading_session, TurnState.failed,
        TurnState.interrupted, TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.loading_session: {
        TurnState.building_context, TurnState.failed,
        TurnState.interrupted, TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.building_context: {
        TurnState.model_calling, TurnState.failed,
        TurnState.interrupted, TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.model_calling: {
        TurnState.composing_result, TurnState.planning_tool,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.planning_tool: {
        TurnState.policy_checking, TurnState.composing_result,
        TurnState.model_calling,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.policy_checking: {
        TurnState.executing_capability, TurnState.waiting_approval,
        TurnState.model_calling,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.waiting_approval: {
        TurnState.executing_capability, TurnState.denied,
        TurnState.interrupted, TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.executing_capability: {
        TurnState.updating_context, TurnState.retrying,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.updating_context: {
        TurnState.model_calling, TurnState.composing_result,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.composing_result: {
        TurnState.extracting_memory, TurnState.model_calling,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.extracting_memory: {
        TurnState.completed, TurnState.failed,
        TurnState.interrupted, TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.retrying: {
        TurnState.model_calling, TurnState.executing_capability,
        TurnState.failed, TurnState.interrupted,
        TurnState.cancelled, TurnState.budget_exceeded,
    },
    TurnState.interrupted: {
        TurnState.resuming, TurnState.cancelled, TurnState.failed,
    },
    TurnState.resuming: {
        TurnState.loading_session, TurnState.building_context,
        TurnState.model_calling, TurnState.executing_capability,
        TurnState.failed,
    },
    TurnState.completed: {TurnState.received},
    TurnState.failed: {TurnState.received},
    TurnState.denied: {TurnState.received},
    TurnState.cancelled: {TurnState.received},
    TurnState.budget_exceeded: {TurnState.received},
}


class TurnStateMachine:
    def __init__(self) -> None:
        self._state: TurnState = TurnState.received

    @property
    def state(self) -> TurnState:
        return self._state

    def transition(self, target: TurnState) -> None:
        allowed = _TRANSITIONS.get(self._state, set())
        if target not in allowed:
            msg = f"Invalid transition: {self._state.value} -> {target.value}"
            raise ValueError(msg)
        self._state = target
