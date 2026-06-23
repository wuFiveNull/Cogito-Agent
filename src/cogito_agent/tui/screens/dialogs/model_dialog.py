"""Model selection dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ModelDialog(ModalScreen):
    """Model chooser dialog."""

    DEFAULT_CSS = """
    ModelDialog {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Model Selection (coming soon)")

    def on_mount(self) -> None:
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
