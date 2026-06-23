"""Thinking message renderer — ``item.type == "thinking"``.

Gemini-cli's ``ThinkingMessage`` equivalent: shows an animated indicator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from . import factory as _factory

if TYPE_CHECKING:
    pass


@_factory.register("thinking")
class ThinkingMessage(Static):
    """Renders a thinking indicator (model is reasoning)."""

    DEFAULT_CSS = """
    ThinkingMessage {
        width: 100%;
        padding: 0 2;
        color: $accent;
    }
    """

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        text = message.get("text", message.get("content", "Thinking..."))
        self.update(f"  ⟳ {text}")
