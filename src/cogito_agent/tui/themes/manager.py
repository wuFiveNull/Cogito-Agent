"""Theme manager — wraps Textual's built-in theme system.

Leverages ``App.register_theme()`` and ``App.theme`` for live switching.
Only standard Textual theme properties are used (``$surface``, ``$text``, etc.).
"""

from __future__ import annotations

from typing import Any

from textual.theme import Theme


class ThemeManager:
    """Manages Cogito TUI themes using Textual's built-in system."""

    @staticmethod
    def builtin_themes() -> dict[str, dict[str, Any]]:
        """Return the built-in theme definitions."""
        return {
            "cogito-dark": {
                "primary": "#6366f1",
                "secondary": "#818cf8",
                "accent": "#a78bfa",
                "surface": "#1a1a2e",
                "error": "#ef4444",
                "success": "#22c55e",
                "warning": "#f59e0b",
                "dark": True,
            },
            "cogito-light": {
                "primary": "#6366f1",
                "secondary": "#818cf8",
                "accent": "#6366f1",
                "surface": "#ffffff",
                "error": "#dc2626",
                "success": "#16a34a",
                "warning": "#d97706",
                "dark": False,
            },
        }

    @staticmethod
    def register_all(app: Any) -> None:
        """Register all built-in themes on the Textual app."""
        for name, vals in ThemeManager.builtin_themes().items():
            try:
                theme = Theme(
                    name=name,
                    primary=vals.get("primary", "#7c3aed"),
                    secondary=vals.get("secondary", "#6366f1"),
                    accent=vals.get("accent", "#a78bfa"),
                    surface=vals.get("surface", "#1a1a2e"),
                    error=vals.get("error", "#ef4444"),
                    success=vals.get("success", "#22c55e"),
                    warning=vals.get("warning", "#f59e0b"),
                    dark=vals.get("dark", True),
                )
                app.register_theme(theme)
            except Exception:
                pass  # Theme already registered — ignore

    @staticmethod
    def set_active(app: Any, name: str) -> None:
        """Activate a theme by name, falling back to 'cogito-dark'."""
        available = list(app.available_themes.keys())
        if name not in available:
            name = "cogito-dark"
        app.theme = name

    @staticmethod
    def available_names(app: Any) -> list[str]:
        """Return names of registered themes that match our naming."""
        return [
            name for name in app.available_themes
            if name.startswith("cogito-")
        ]
