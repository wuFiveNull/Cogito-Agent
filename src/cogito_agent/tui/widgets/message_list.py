"""Virtualized message history — mirrors gemini-cli's ``MainContent``.

Manages a ``VerticalScroll`` of ``MessageItem`` widgets with
auto-scroll-to-bottom behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll
from textual.reactive import reactive

if TYPE_CHECKING:
    pass


class MessageList(VerticalScroll):
    """Scrollable message history container.

    Watches a list of message dicts and mounts/unmounts
    ``MessageItem`` widgets accordingly.
    """

    messages: reactive[list[dict[str, Any]]] = reactive(list, layout=True)

    def __init__(self, store: Any | None = None, **kwargs: Any) -> None:
        self._store = store
        self._user_scrolled_up = False
        super().__init__(**kwargs)

    DEFAULT_CSS = """
    MessageList {
        height: 1fr;
        overflow-y: auto;
        background: $surface;
    }
    """

    def on_mount(self) -> None:
        if self._store and self._store.messages:
            self.messages = list(self._store.messages)
        self.scroll_end(animate=False)

    def watch_messages(self, messages: list[dict[str, Any]]) -> None:
        """React to message list changes — mount new messages."""
        self._remove_orphan_widgets(messages)
        for msg in messages:
            if not self._widget_for_message(msg):
                self._mount_message(msg)
        self._handle_auto_scroll()
        self.refresh(layout=True)

    def _remove_orphan_widgets(self, messages: list[dict[str, Any]]) -> None:
        """Unmount widgets whose message IDs are no longer in the list."""
        active_ids = {m.get("id", "") for m in messages}
        for child in list(self.children):
            mid = getattr(child, "message_id", "")
            if mid and mid not in active_ids:
                child.remove()

    def _widget_for_message(self, msg: dict[str, Any]) -> bool:
        mid = msg.get("id", "")
        return any(getattr(c, "message_id", "") == mid for c in self.children)

    def _mount_message(self, msg: dict[str, Any]) -> None:
        from .message_item import MessageItem
        self.mount(MessageItem(msg))

    def _handle_auto_scroll(self) -> None:
        """Scroll to bottom unless the user has manually scrolled up."""
        if not self._user_scrolled_up:
            self.scroll_end(animate=False)

    def on_scroll(self) -> None:
        """Detect user scroll-up to pause auto-scroll."""
        near_bottom = self.scroll_y >= (self.max_scroll_y - 1)
        self._user_scrolled_up = not near_bottom

    def scroll_to_bottom(self) -> None:
        """User-initiated scroll to bottom, re-enables auto-scroll."""
        self._user_scrolled_up = False
        self.scroll_end(animate=True)
