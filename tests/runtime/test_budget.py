from cogito_agent.runtime import TurnBudget


def test_default_budget() -> None:
    b = TurnBudget()
    assert b.max_model_calls == 10
    assert b.max_tool_calls == 2


def test_model_call_limit() -> None:
    b = TurnBudget(max_model_calls=2)
    assert b.can_call_model(0) is True
    assert b.can_call_model(1) is True
    assert b.can_call_model(2) is False


def test_tool_call_limit() -> None:
    b = TurnBudget(max_tool_calls=1)
    assert b.can_call_tool(0) is True
    assert b.can_call_tool(1) is False
