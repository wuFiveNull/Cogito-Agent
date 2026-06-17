"""Tests: model.streaming_enabled config flag controls streaming behavior."""
from __future__ import annotations

from unittest.mock import MagicMock

from cogito_agent.models import ModelAdapter, ModelResponse, StreamGenerator


def _mock_adapter(supports: bool = True) -> MagicMock:
    m = MagicMock(spec=ModelAdapter)
    m.supports_streaming = supports
    m.chat.return_value = ModelResponse(content="full response")
    m.stream_chat.return_value = iter(["token1", " ", "token2"])
    return m


def test_streaming_enabled_true_calls_stream_chat():
    adapter = _mock_adapter(supports=True)
    gen = StreamGenerator(adapter, [{"role": "user", "content": "hi"}],
                          streaming_enabled=True)
    tokens = list(gen)
    adapter.stream_chat.assert_called_once()
    adapter.chat.assert_not_called()
    assert len(tokens) == 3
    assert "".join(tokens) == "token1 token2"


def test_streaming_enabled_false_calls_chat():
    adapter = _mock_adapter(supports=True)
    gen = StreamGenerator(adapter, [{"role": "user", "content": "hi"}],
                          streaming_enabled=False)
    tokens = list(gen)
    adapter.stream_chat.assert_not_called()
    adapter.chat.assert_called_once()
    assert len(tokens) == 1
    assert tokens[0] == "full response"


def test_streaming_enabled_true_adapter_no_streaming():
    adapter = _mock_adapter(supports=False)
    gen = StreamGenerator(adapter, [{"role": "user", "content": "hi"}],
                          streaming_enabled=True)
    tokens = list(gen)
    adapter.stream_chat.assert_not_called()
    adapter.chat.assert_called_once()
    assert len(tokens) == 1


def test_streaming_enabled_false_adapter_no_streaming():
    adapter = _mock_adapter(supports=False)
    gen = StreamGenerator(adapter, [{"role": "user", "content": "hi"}],
                          streaming_enabled=False)
    tokens = list(gen)
    adapter.stream_chat.assert_not_called()
    adapter.chat.assert_called_once()
    assert len(tokens) == 1


def test_streaming_enabled_default_true():
    adapter = _mock_adapter(supports=True)
    gen = StreamGenerator(adapter, [{"role": "user", "content": "hi"}])
    list(gen)
    adapter.stream_chat.assert_called_once()


def test_no_adapter_echo():
    gen = StreamGenerator(None, [], echo_text="echo response")
    tokens = list(gen)
    assert "".join(tokens) == "echo response"
    assert gen.response is not None
    assert gen.response.content == "echo response"
