"""Status bar footer — shows model, session, and connection info.

Mirrors gemini-cli's ``Footer`` component.
"""

from __future__ import annotations

from typing import Any

from textual.widgets import Static


class TuiFooter(Static):
    """Bottom status bar — one line, always visible.

    Shows: model name | session ID (short) | workspace
    """

    DEFAULT_CSS = """
    TuiFooter {
        width: 100%;
        height: 1;
        background: $surface;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        self._update_text()

    def _update_text(self) -> None:
        app = self.app
        ws = getattr(app, "workspace_id", "?")
        sid = getattr(app, "session_id", "?")
        short_sid = sid[:8] if sid != "?" else "?"
        import os
        model = os.environ.get("MODEL_NAME", "default")
        self.update(f"  Model: {model}  |  Session: {short_sid}  |  Workspace: {ws}")
