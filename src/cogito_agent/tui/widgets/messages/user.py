"""User message renderer — ``item.type == "user"``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from . import factory as _factory

if TYPE_CHECKING:
    pass


@_factory.register("user")
class UserMessage(Static):
    """Renders a user chat message."""

    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        padding: 0 2;
        color: $text;
        background: $boost;
    }
    """

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        content = message.get("content", message.get("text", ""))
        self.update(f"  You: {content}")
