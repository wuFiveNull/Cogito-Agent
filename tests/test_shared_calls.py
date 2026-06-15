from cogito_agent.shared import ModelCall, ToolCall


def test_tool_call_defaults() -> None:
    tc = ToolCall(trace_id="t-1", span_id="s-1", capability_name="test")
    assert tc.id is not None
    assert tc.status == ""


def test_model_call_defaults() -> None:
    mc = ModelCall(trace_id="t-1", span_id="s-1")
    assert mc.id is not None
    assert mc.provider == ""
