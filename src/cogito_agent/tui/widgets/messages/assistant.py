"""Assistant message renderer — ``item.type == "assistant"``.

Supports in-place token-by-token updates during streaming.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from . import factory as _factory

if TYPE_CHECKING:
    pass


@_factory.register("assistant")
class AssistantMessage(Static):
    """Renders an AI response message.

    During streaming, call ``append_token(token)`` to add text
    incrementally.
    """

    DEFAULT_CSS = """
    AssistantMessage {
        width: 100%;
        padding: 0 2;
        color: $text;
        background: $boost;
    }
    """

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        self._full_content = message.get("content", message.get("text", ""))
        self.update(self._format_content(self._full_content))

    def _format_content(self, content: str) -> str:
        return f"  AI: {content}"

    def append_token(self, token: str) -> None:
        """Append a streaming token and refresh."""
        self._full_content += token
        self.update(self._format_content(self._full_content))
