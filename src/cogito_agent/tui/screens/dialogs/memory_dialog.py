"""Memory browser dialog — lists/search memories."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class MemoryDialog(ModalScreen):
    """Memory browser dialog."""

    DEFAULT_CSS = """
    MemoryDialog {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Memory Browser (coming soon)")

    def on_mount(self) -> None:
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
