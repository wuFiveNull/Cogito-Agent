"""Tests: ToolIntent parsing and ModelResponse backward compatibility."""

from __future__ import annotations

from cogito_agent.models import ModelResponse, ToolIntent


def test_tool_intent_creation() -> None:
    intent = ToolIntent(
        tool_call_id="call_123",
        capability_name="read_file",
        arguments={"path": "/test.txt"},
    )
    assert intent.tool_call_id == "call_123"
    assert intent.capability_name == "read_file"
    assert intent.arguments == {"path": "/test.txt"}


def test_model_response_with_tool_intents() -> None:
    intents = [
        ToolIntent(tool_call_id="c1", capability_name="tool_a", arguments={}),
    ]
    resp = ModelResponse(content="", tool_intents=intents)
    assert resp.has_tool_calls
    assert resp.get_tool_call_ids() == ["c1"]


def test_model_response_no_tool_calls() -> None:
    resp = ModelResponse(content="Hello")
    assert not resp.has_tool_calls
    assert resp.get_tool_call_ids() == []


def test_legacy_dict_backward_compat() -> None:
    resp = ModelResponse(
        content="",
        tool_intents=[{"name": "read_file", "arguments": {"path": "/x"}}],
    )
    assert resp.has_tool_calls
    assert resp.tool_intents[0].capability_name == "read_file"
    assert resp.tool_intents[0].arguments == {"path": "/x"}


def test_legacy_dict_with_string_arguments() -> None:
    resp = ModelResponse(
        content="",
        tool_intents=[{"name": "test", "arguments": '{"key": "val"}'}],
    )
    assert resp.tool_intents[0].capability_name == "test"
    assert resp.tool_intents[0].arguments == {"key": "val"}


def test_legacy_dict_empty() -> None:
    resp = ModelResponse(content="No tools")
    assert not resp.has_tool_calls


def test_tool_intent_equality() -> None:
    a = ToolIntent(tool_call_id="c1", capability_name="tool", arguments={"a": 1})
    b = ToolIntent(tool_call_id="c1", capability_name="tool", arguments={"a": 1})
    assert a.tool_call_id == b.tool_call_id
    assert a.capability_name == b.capability_name
