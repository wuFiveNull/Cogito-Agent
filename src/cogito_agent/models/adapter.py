from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ModelResponse:
    content: str = ""
    tool_intents: list[dict[str, object]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    stop_reason: str = ""
    error: str | None = None


class ModelAdapter(Protocol):
    supports_streaming: bool = False

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> ModelResponse: ...

    def stream_chat(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> Iterator[str]: ...


class StreamGenerator:
    """Wraps a model adapter call to yield token deltas.

    After iteration, ``.response`` holds the full ``ModelResponse``.
    """

    def __init__(
        self,
        adapter: ModelAdapter | None,
        messages: list[dict[str, str]],
        echo_text: str = "",
    ) -> None:
        self._adapter = adapter
        self._messages = messages
        self._echo_text = echo_text
        self.response: ModelResponse | None = None

    def __iter__(self) -> Iterator[str]:
        if self._adapter is None:
            if self._echo_text:
                yield self._echo_text
            self.response = ModelResponse(content=self._echo_text)
            return
        supports = getattr(self._adapter, "supports_streaming", None)
        if supports is True:
            collected: list[str] = []
            for chunk in self._adapter.stream_chat(self._messages):
                collected.append(chunk)
                yield chunk
            full = "".join(collected)
            self.response = ModelResponse(
                content=full,
                model=getattr(self._adapter, "model", ""),
            )
        else:
            self.response = self._adapter.chat(self._messages)
            if self.response and self.response.content:
                yield self.response.content
