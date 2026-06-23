"""Type-dispatch message renderer — mirrors gemini-cli's ``HistoryItemDisplay``.

Routes each message to its type-specific widget via the ``factory`` registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from .messages import assistant as _assistant  # noqa: F401

# Import all message renderers so they register with the factory
from .messages import factory as _factory
from .messages import info as _info  # noqa: F401
from .messages import thinking as _thinking  # noqa: F401
from .messages import tool as _tool  # noqa: F401
from .messages import user as _user  # noqa: F401

if TYPE_CHECKING:
    pass


class MessageItem(Static):
    """Renders a single message by dispatching to a type-specific widget.

    Matches gemini-cli's ``HistoryItemDisplay`` which uses a chain of
    ``if item.type == "user": return <UserMessage>`` conditions.
    """

    def __init__(self, message: dict[str, Any]) -> None:
        self.message = message
        self.message_id = message.get("id", "")
        super().__init__()

    def on_mount(self) -> None:
        handler = self._get_handler()
        if handler:
            self._render_handler(handler)

    def _get_handler(self) -> type[Static] | None:
        """Find the widget class for this message type."""
        msg_type = self.message.get("type", "info")
        return _factory.get_handler(msg_type)

    def _render_handler(self, handler_cls: type[Static]) -> None:
        """Replace placeholder content with the dispatched widget."""
        widget = handler_cls(self.message)
        self.remove_children()
        self.mount(widget)
