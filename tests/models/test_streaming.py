from __future__ import annotations

import json
import unittest.mock
from urllib.error import HTTPError

from cogito_agent.models.openai_adapter import OpenAICompatibleAdapter


def _make_sse_chunks(tokens: list[str]) -> bytes:
    lines = []
    for token in tokens:
        data = json.dumps({"choices": [{"delta": {"content": token}}]})
        lines.append(f"data: {data}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


class _MockStream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + (size if size > 0 else len(self._data))]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> _MockStream:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_stream_chat_yields_tokens() -> None:
    adapter = OpenAICompatibleAdapter(
        api_key="test-key",
        base_url="http://fake.example/v1",
        model="test-model",
    )

    chunks = _make_sse_chunks(["hello", " world", "!"])
    mock_stream = _MockStream(chunks)

    with unittest.mock.patch("urllib.request.urlopen", return_value=mock_stream):
        tokens = list(adapter.stream_chat([{"role": "user", "content": "hi"}]))
        assert tokens == ["hello", " world", "!"]


def test_stream_chat_empty() -> None:
    adapter = OpenAICompatibleAdapter(
        api_key="test-key",
        base_url="http://fake.example/v1",
        model="test-model",
    )

    chunks = _make_sse_chunks([])
    mock_stream = _MockStream(chunks)

    with unittest.mock.patch("urllib.request.urlopen", return_value=mock_stream):
        tokens = list(adapter.stream_chat([{"role": "user", "content": "hi"}]))
        assert tokens == []


def test_stream_chat_http_error() -> None:
    adapter = OpenAICompatibleAdapter(
        api_key="test-key",
        base_url="http://fake.example/v1",
        model="test-model",
    )

    def _raise_error(*args: object, **kwargs: object) -> object:
        raise HTTPError(
            "http://fake.example/v1/chat/completions",
            500,
            "Internal Server Error",
            {},
            None,
        )

    with unittest.mock.patch("urllib.request.urlopen", side_effect=_raise_error):
        tokens = list(adapter.stream_chat([{"role": "user", "content": "hi"}]))
        assert len(tokens) == 1
        assert "stream error" in tokens[0]
