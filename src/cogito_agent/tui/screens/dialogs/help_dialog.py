"""Help dialog — keybinding reference and usage info."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class HelpDialog(ModalScreen):
    """Help / keybinding reference dialog."""

    DEFAULT_CSS = """
    HelpDialog {
        align: center middle;
    }
    #help-box {
        width: 60;
        height: auto;
        padding: 1;
        background: $surface;
        border: thick $accent;
    }
    #help-box > Label {
        margin-bottom: 1;
    }
    """

    COMMANDS = [
        ("/help", "Show this help dialog"),
        ("/theme", "Open theme selector"),
        ("/settings", "Show settings"),
        ("/model", "Select model"),
        ("/session", "Browse sessions"),
        ("/memory [list|search|add]", "Memory operations"),
        ("/clear", "Clear the chat screen"),
        ("/quit", "Exit the application"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("[bold]Cogito TUI — Commands[/]")

    def on_mount(self) -> None:
        for cmd, desc in self.COMMANDS:
            self.mount(Label(f"  [bold]{cmd}[/]  — {desc}"))
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
