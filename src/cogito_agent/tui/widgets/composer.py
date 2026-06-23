"""Bottom composer area — mirrors gemini-cli's ``Composer`` component.

Contains the input prompt, status indicators, and submission wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from .input_prompt import InputPrompt


class StatusRow(Static):
    """Status indicators: streaming spinner, model name, mode."""

    DEFAULT_CSS = """
    StatusRow {
        width: 100%;
        height: 1;
        background: $surface;
        color: $text-disabled;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.update("  Ready")


class Composer(Horizontal):
    """Bottom control area — input prompt + status.

    Layout:
      StatusRow  [1 line]
      InputPrompt [up to 5 lines]
    """

    DEFAULT_CSS = """
    Composer {
        width: 100%;
        height: auto;
        max-height: 6;
        background: $boost;
        layout: vertical;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        self._status_row = StatusRow()
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        from .input_prompt import InputPrompt
        yield self._status_row
        yield InputPrompt(id="chat-input")

    @property
    def input_prompt(self) -> InputPrompt | None:
        return self.query_one("#chat-input", InputPrompt)

    async def on_input_prompt_submitted(self, message: InputPrompt.Submitted) -> None:
        """Handle input submission — forward to the parent screen."""
        text = message.value
        if not text:
            return
        # Bubble up to the ChatScreen
        self.screen.post_message(self.SubmitMessage(text))

    class SubmitMessage(Message):
        """Posted by Composer when the user submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text
