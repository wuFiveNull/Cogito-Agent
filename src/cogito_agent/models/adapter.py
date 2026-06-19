from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolIntent:
    """A structured tool call requested by the model via native function calling."""

    tool_call_id: str
    capability_name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass
class ModelResponse:
    content: str = ""
    tool_intents: list[ToolIntent] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    latency_ms: int = 0
    stop_reason: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        if self.tool_intents and isinstance(self.tool_intents[0], dict):
            self.tool_intents = ModelResponse.from_legacy_dicts(
                self.tool_intents  # type: ignore[arg-type]
            )

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_intents) > 0

    def get_tool_call_ids(self) -> list[str]:
        return [t.tool_call_id for t in self.tool_intents]

    @staticmethod
    def from_legacy_dicts(intents: list[dict[str, object]]) -> list[ToolIntent]:
        """Convert legacy dict-style intents to ToolIntent objects."""
        results: list[ToolIntent] = []
        for intent in intents:
            name = str(intent.get("name", intent.get("function", "")))
            args_raw = intent.get("arguments", {})
            if isinstance(args_raw, str):
                import json
                try:
                    args = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            elif isinstance(args_raw, dict):
                args = {str(k): v for k, v in args_raw.items()}
            else:
                args = {}
            results.append(ToolIntent(
                tool_call_id=str(intent.get("id", intent.get("tool_call_id", ""))),
                capability_name=name,
                arguments=args,
            ))
        return results


class ModelAdapter(Protocol):
    supports_streaming: bool = False

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> ModelResponse: ...

    def stream_chat(
        self, messages: list[dict[str, object]], **kwargs: object
    ) -> Iterator[str]: ...


class StreamGenerator:
    """Wraps a model adapter call to yield token deltas.

    After iteration, ``.response`` holds the full ``ModelResponse``.
    Supports streaming tool calls: the adapter may yield "[TOOL_CALLS]"
    as a sentinel to indicate tool calls were accumulated during stream.
    """

    def __init__(
        self,
        adapter: ModelAdapter | None,
        messages: list[dict[str, object]],
        echo_text: str = "",
        streaming_enabled: bool = True,
        tool_schemas: list[dict[str, object]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._messages = messages
        self._echo_text = echo_text
        self._streaming_enabled = streaming_enabled
        self._tool_schemas = tool_schemas
        self.response: ModelResponse | None = None

    def __iter__(self) -> Iterator[str]:
        kwargs: dict[str, object] = {}
        if self._tool_schemas:
            kwargs["tools"] = self._tool_schemas

        if self._adapter is None:
            if self._echo_text:
                yield self._echo_text
            self.response = ModelResponse(content=self._echo_text)
            return
        supports = getattr(self._adapter, "supports_streaming", None)
        if supports is True and self._streaming_enabled:
            collected: list[str] = []
            tool_call_sentinel = False
            for chunk in self._adapter.stream_chat(self._messages, **kwargs):
                if chunk == "[TOOL_CALLS]":
                    tool_call_sentinel = True
                    continue
                collected.append(chunk)
                yield chunk
            full = "".join(collected)
            # Try to get tool calls from streaming adapter
            tool_intents: list[ToolIntent] = []
            if tool_call_sentinel:
                get_tc = getattr(self._adapter, "get_tool_calls_from_stream", None)
                if get_tc:
                    tool_intents = get_tc()
                else:
                    tool_intents = list(getattr(self._adapter, "_tool_intents", []))
            self.response = ModelResponse(
                content=full,
                tool_intents=tool_intents,
                model=getattr(self._adapter, "model", ""),
            )
        else:
            self.response = self._adapter.chat(self._messages, **kwargs)
            if self.response and self.response.content:
                yield self.response.content
