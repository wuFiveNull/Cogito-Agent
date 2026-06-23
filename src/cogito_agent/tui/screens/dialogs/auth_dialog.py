"""Auth dialog — for API key / authentication setup."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class AuthDialog(ModalScreen):
    """Authentication setup dialog."""

    DEFAULT_CSS = """
    AuthDialog {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Authentication (coming soon)")

    def on_mount(self) -> None:
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
