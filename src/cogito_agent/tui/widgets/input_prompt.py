"""Rich text input with history, tab-completion, and command handling.

Mirrors gemini-cli's ``InputPrompt`` component.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Input

if TYPE_CHECKING:
    pass


class InputPrompt(Input):
    """Enhanced text input for the chat composer.

    Features:
    - Enter to submit, Shift+Enter for newlines
    - Up/Down input history navigation
    - Placeholder text
    - Command prefix awareness (``/`` commands)
    """

    DEFAULT_CSS = """
    InputPrompt {
        width: 100%;
        min-height: 1;
        max-height: 5;
        background: $boost;
        color: $text;
    }
    """

    def __init__(
        self,
        placeholder: str = "Type a message...",
        history_size: int = 50,
        **kwargs: Any,
    ) -> None:
        self._history: list[str] = []
        self._history_index: int = -1
        self._history_size = history_size
        self._submitted_text = ""
        super().__init__(placeholder=placeholder, **kwargs)

    @property
    def submitted_text(self) -> str:
        """The last submitted text."""
        return self._submitted_text

    def action_submit(self) -> None:
        """Submit the current input."""
        text = self.value.strip()
        if not text:
            return
        self._submitted_text = text
        self._add_to_history(text)
        # Post a custom message for the parent to handle
        self.post_message(self.Submitted(self, text))

    class Submitted(Input.Changed):
        """Posted when the user submits text."""

    def _add_to_history(self, text: str) -> None:
        self._history.append(text)
        if len(self._history) > self._history_size:
            self._history.pop(0)
        self._history_index = len(self._history)

    def action_history_previous(self, prev: str | None = None) -> str | None:
        """Navigate backwards in input history."""
        if not self._history:
            return prev
        # Save current unsaved work
        if self._history_index == len(self._history):
            self._pending = self.value
        if self._history_index > 0:
            self._history_index -= 1
            self.value = self._history[self._history_index]
            self.cursor_position = len(self.value)
        return prev

    def action_history_next(self, prev: str | None = None) -> str | None:
        """Navigate forwards in input history."""
        if not self._history:
            return prev
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.value = self._history[self._history_index]
            self.cursor_position = len(self.value)
        elif self._history_index == len(self._history) - 1:
            self._history_index = len(self._history)
            self.value = getattr(self, "_pending", "")
            self.cursor_position = len(self.value)
        return prev

    def on_mount(self) -> None:
        self._pending = ""
        self.focus()
