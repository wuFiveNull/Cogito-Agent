"""Priority-based modal dialog controller — mirrors gemini-cli's DialogManager.

Uses a priority-ordered chain: the first dialog whose flag is ``True``
gets pushed as a modal screen. All others wait.

Usage::

    # In app.py, call ``DialogManager.watch(app)`` to start watching.
    # Set ``app.tui_state.show_theme_dialog = True`` to open the dialog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.screen import ModalScreen

if TYPE_CHECKING:
    from textual.app import App


class DialogManager:
    """Watches reactive flags and pushes/pops modal dialog screens.

    Works with ``TUIState`` dialog flags (``show_*_dialog``) and
    the shared ``dialogs_visible`` flag.
    """

    # Priority descending — first match wins
    PRIORITY: ClassVar[list[tuple[str, type[ModalScreen]]]] = [
        ("show_auth_dialog", None),  # Will be imported lazily
        ("show_theme_dialog", None),
        ("show_settings_dialog", None),
        ("show_model_dialog", None),
        ("show_session_dialog", None),
        ("show_memory_dialog", None),
        ("show_confirm_dialog", None),
        ("show_help_dialog", None),
    ]

    def __init__(self, app: App) -> None:
        self._app = app

    def get_active_dialog_cls(self) -> type[ModalScreen] | None:
        """Return highest-priority dialog class whose flag is set, or None."""
        state = self._get_state()
        if not state:
            return None
        for flag_name, _dialog_cls in self.PRIORITY:
            if getattr(state, flag_name, False):
                return self._resolve_dialog(flag_name)
        return None

    def has_active_flag(self) -> bool:
        """Check if any dialog flag is set."""
        state = self._get_state()
        if not state:
            return False
        return any(getattr(state, flag_name, False) for flag_name, _ in self.PRIORITY)

    def dismiss_current(self) -> None:
        """Pop the current modal screen and reset its flag."""
        screens = self._app.screen_stack
        if len(screens) > 1:
            self._app.pop_screen()
        self._reset_all_flags()

    def _get_state(self) -> object | None:
        return getattr(self._app, "tui_state", None)

    def _resolve_dialog(self, flag_name: str) -> type[ModalScreen] | None:
        """Lazy-import and return the dialog class for a flag."""
        from . import messages as _msg  # noqa: F401
        _lazy = _resolve_class
        _map: dict[str, type[ModalScreen]] = {
            "show_theme_dialog": _lazy("ThemeDialog", "screens.dialogs.theme_dialog"),
            "show_settings_dialog": _lazy("SettingsDialog", "screens.dialogs.settings_dialog"),
            "show_model_dialog": _lazy("ModelDialog", "screens.dialogs.model_dialog"),
            "show_session_dialog": _lazy("SessionDialog", "screens.dialogs.session_dialog"),
            "show_memory_dialog": _lazy("MemoryDialog", "screens.dialogs.memory_dialog"),
            "show_confirm_dialog": _lazy("ConfirmDialog", "screens.dialogs.confirm_dialog"),
            "show_help_dialog": _lazy("HelpDialog", "screens.dialogs.help_dialog"),
            "show_auth_dialog": _lazy("AuthDialog", "screens.dialogs.auth_dialog"),
        }
        return _map.get(flag_name)

    def _reset_all_flags(self) -> None:
        state = self._get_state()
        if state:
            for flag_name, _ in self.PRIORITY:
                setattr(state, flag_name, False)
            state.dialogs_visible = False  # type: ignore[attr-defined]


def _resolve_class(class_name: str, rel_module: str) -> type[ModalScreen] | None:
    """Lazy-import a class from a relative ``cogito_agent.tui.`` module."""
    import importlib
    try:
        mod = importlib.import_module(f"cogito_agent.tui.{rel_module}")
        return getattr(mod, class_name, None)
    except (ImportError, AttributeError):
        return None
