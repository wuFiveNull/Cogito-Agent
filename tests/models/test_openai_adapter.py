from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from cogito_agent.models import OpenAICompatibleAdapter


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__.return_value = mock
    if status != 200:
        raise __import__("urllib.error").HTTPError(
            "http://example.com", status, "Error", {}, None
        )
    return mock


@patch("cogito_agent.models.openai_adapter.urllib.request.urlopen")
def test_chat_success(mock_urlopen: MagicMock) -> None:
    mock_urlopen.return_value = _mock_response({
        "id": "chatcmpl-xxx",
        "model": "gpt-4o-mini",
        "choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })
    adapter = OpenAICompatibleAdapter(api_key="test-key", model="gpt-4o-mini")
    resp = adapter.chat([{"role": "user", "content": "Hi"}])
    assert resp.content == "Hello!"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5
    assert resp.error is None


@patch("cogito_agent.models.openai_adapter.urllib.request.urlopen")
def test_chat_tool_intent(mock_urlopen: MagicMock) -> None:
    mock_urlopen.return_value = _mock_response({
        "id": "chatcmpl-xxx",
        "model": "gpt-4o-mini",
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "read_file", "arguments": "{}"},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })
    adapter = OpenAICompatibleAdapter(api_key="test-key", model="gpt-4o-mini")
    resp = adapter.chat([{"role": "user", "content": "Read a file"}])
    assert len(resp.tool_intents) == 1
    assert resp.tool_intents[0]["function"] == "read_file"
    assert resp.stop_reason == "tool_calls"


@patch("cogito_agent.models.openai_adapter.urllib.request.urlopen")
def test_chat_http_error(mock_urlopen: MagicMock) -> None:
    import urllib.error

    error_resp = MagicMock()
    error_resp.read.return_value = b'{"error": "rate limited"}'
    error_resp.__enter__.return_value = error_resp
    mock_urlopen.side_effect = urllib.error.HTTPError(
        "http://example.com", 429, "Too Many Requests", {}, error_resp
    )
    adapter = OpenAICompatibleAdapter(api_key="test-key", model="gpt-4o-mini")
    resp = adapter.chat([{"role": "user", "content": "Hi"}])
    assert resp.error is not None
    assert "429" in resp.error
