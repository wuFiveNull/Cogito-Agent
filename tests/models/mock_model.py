"""MockModel adapter for testing true per-token streaming.

Provides a model adapter that:
- Supports streaming (supports_streaming = True)
- Emits multiple delta tokens on stream_chat()
- Returns the full response via chat()
"""

from __future__ import annotations

from collections.abc import Iterator

from cogito_agent.models import ModelResponse, ToolIntent


def _split_tokens(text: str) -> list[str]:
    """Split text into per-word tokens for realistic multi-delta streaming."""
    tokens: list[str] = []
    for word in text.split(" "):
        if tokens:
            tokens.append(" ")
        tokens.append(word)
    return tokens


class MockModel:
    """Mock model adapter that provides true streaming for testing.

    Usage:
        adapter = MockModel(response_text="Hello world!")
        for chunk in adapter.stream_chat([{"role": "user", "content": "hi"}]):
            print(chunk, end="")
    """

    supports_streaming: bool = True
    provider: str = "mock"
    model: str = "mock-model"
    _accumulated_tool_calls: dict[int, dict[str, object]] | None = None

    def __init__(
        self,
        response_text: str = "Mock response for testing purposes.",
        tool_intents: list[ToolIntent] | None = None,
        fail_on_prompt: str | None = None,
    ) -> None:
        self._response_text = response_text
        self._tool_intents = tool_intents or []
        self._fail_on_prompt = fail_on_prompt

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> ModelResponse:
        prompt = messages[-1]["content"] if messages else ""
        if self._fail_on_prompt and self._fail_on_prompt in prompt:
            return ModelResponse(
                content="", error=f"Mock failure triggered by: {self._fail_on_prompt}"
            )
        return ModelResponse(
            content=self._response_text,
            tool_intents=list(self._tool_intents),
            input_tokens=len(prompt.split()),
            output_tokens=len(self._response_text.split()),
            model=self.model,
            provider=self.provider,
        )

    def stream_chat(self, messages: list[dict[str, object]], **kwargs: object) -> Iterator[str]:
        prompt = messages[-1]["content"] if messages else ""
        if self._fail_on_prompt and self._fail_on_prompt in prompt:
            raise RuntimeError(f"MockModel triggered failure: {self._fail_on_prompt}")

        # If there are tool intents, yield content then sentinel
        if self._tool_intents:
            if self._response_text:
                for token in _split_tokens(self._response_text):
                    yield token
            yield "[TOOL_CALLS]"
            return

        tokens = _split_tokens(self._response_text)
        for token in tokens:
            yield token
