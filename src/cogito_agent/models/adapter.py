from __future__ import annotations

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
    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> ModelResponse: ...
