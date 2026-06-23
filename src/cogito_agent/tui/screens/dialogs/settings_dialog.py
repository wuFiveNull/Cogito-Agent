"""Settings dialog — read-only config view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class SettingsDialog(ModalScreen):
    """Settings viewer dialog."""

    DEFAULT_CSS = """
    SettingsDialog {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Settings (coming soon)")

    def on_mount(self) -> None:
        self._add_close_button()

    def _add_close_button(self) -> None:
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
