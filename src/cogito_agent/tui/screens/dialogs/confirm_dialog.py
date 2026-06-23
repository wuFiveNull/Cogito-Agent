"""Generic confirmation/approval dialog.

Used for tool approval requests and generic Yes/No confirmations.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmDialog(ModalScreen):
    """Yes/No or Approve/Deny confirmation dialog.

    Placeholder — will be wired to the kernel approval flow.
    """

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-box {
        width: 50;
        height: auto;
        padding: 1;
        background: $surface;
        border: thick $warning;
    }
    #confirm-box > Label {
        text-style: bold;
        margin-bottom: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Confirmation (coming soon)")

    def on_mount(self) -> None:
        self.mount(Button(" Approve ", variant="primary", id="approve"))
        self.mount(Button(" Deny ", variant="error", id="deny"))
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
