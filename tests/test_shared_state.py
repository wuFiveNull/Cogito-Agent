import pytest

from cogito_agent.shared import TurnState, TurnStateMachine


def test_initial_state() -> None:
    sm = TurnStateMachine()
    assert sm.state == TurnState.received


def test_valid_transition() -> None:
    sm = TurnStateMachine()
    sm.transition(TurnState.loading_session)
    assert sm.state == TurnState.loading_session


def test_complete_flow() -> None:
    sm = TurnStateMachine()
    path = [
        TurnState.loading_session,
        TurnState.building_context,
        TurnState.model_calling,
        TurnState.composing_result,
        TurnState.extracting_memory,
        TurnState.completed,
    ]
    for s in path:
        sm.transition(s)
    assert sm.state == TurnState.completed


def test_invalid_transition() -> None:
    sm = TurnStateMachine()
    with pytest.raises(ValueError, match="Invalid transition"):
        sm.transition(TurnState.completed)


def test_terminal_states() -> None:
    for terminal in [TurnState.completed, TurnState.failed, TurnState.denied, TurnState.cancelled]:
        sm = TurnStateMachine()
        path_to_received: list[TurnState] = [TurnState.loading_session, TurnState.failed]
        for s in path_to_received:
            sm.transition(s)
        assert sm.state == TurnState.failed
