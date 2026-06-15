from __future__ import annotations

from enum import StrEnum


class TurnState(StrEnum):
    received = "received"
    loading_session = "loading_session"
    building_context = "building_context"
    awaiting_model = "awaiting_model"
    calling_tool = "calling_tool"
    awaiting_approval = "awaiting_approval"
    evaluating_result = "evaluating_result"
    composing_result = "composing_result"
    persisting = "persisting"
    retrying = "retrying"
    interrupted = "interrupted"
    resuming = "resuming"
    completed = "completed"
    failed = "failed"
    denied = "denied"
    cancelled = "cancelled"


_TRANSITIONS: dict[TurnState, set[TurnState]] = {
    TurnState.received: {TurnState.loading_session, TurnState.failed},
    TurnState.loading_session: {TurnState.building_context, TurnState.failed},
    TurnState.building_context: {TurnState.awaiting_model, TurnState.failed},
    TurnState.awaiting_model: {
        TurnState.evaluating_result, TurnState.calling_tool, TurnState.failed,
    },
    TurnState.calling_tool: {
        TurnState.awaiting_approval, TurnState.evaluating_result,
        TurnState.retrying, TurnState.failed,
    },
    TurnState.awaiting_approval: {TurnState.calling_tool, TurnState.denied, TurnState.interrupted},
    TurnState.evaluating_result: {
        TurnState.composing_result, TurnState.awaiting_model,
        TurnState.calling_tool, TurnState.failed,
    },
    TurnState.composing_result: {TurnState.persisting, TurnState.failed},
    TurnState.persisting: {TurnState.completed, TurnState.failed},
    TurnState.retrying: {TurnState.awaiting_model, TurnState.calling_tool, TurnState.failed},
    TurnState.interrupted: {TurnState.resuming, TurnState.cancelled},
    TurnState.resuming: {
        TurnState.building_context, TurnState.calling_tool, TurnState.awaiting_model,
    },
    TurnState.completed: set(),
    TurnState.failed: set(),
    TurnState.denied: set(),
    TurnState.cancelled: set(),
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
