"""Theme selection dialog — lists available themes, selects on click."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ThemeDialog(ModalScreen):
    """Theme switcher dialog.

    Lists all registered ``cogito-*`` themes and applies the selected one.
    """

    DEFAULT_CSS = """
    ThemeDialog {
        align: center middle;
    }
    #theme-box {
        width: 50;
        height: auto;
        padding: 1;
        background: $surface;
        border: thick $accent;
    }
    #theme-box > Label {
        text-style: bold;
        margin-bottom: 1;
    }
    Label {
        padding: 0 1;
    }
    Label:hover {
        background: $accent 20%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Select Theme[/]")

    def on_mount(self) -> None:
        from ..themes.manager import ThemeManager
        themes = ThemeManager.available_names(self.app)
        for name in themes:
            display = name.replace("cogito-", "").title()
            self.mount(Label(f"  {display}", id=f"theme-{name}"))
        self.mount(Button(" Close ", variant="default", id="close"))

    def on_label_clicked(self, event: Label.Clicked) -> None:
        """Apply the clicked theme."""
        label = event.widget
        theme_name = label.id.replace("theme-", "") if label.id else ""
        if theme_name:
            from ..themes.manager import ThemeManager
            ThemeManager.set_active(self.app, theme_name)
        self._dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._dismiss()

    def _dismiss(self) -> None:
        from ..widgets.dialog_manager import DialogManager
        DialogManager(self.app).dismiss_current()
