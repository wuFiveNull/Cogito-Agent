"""Cogito TUI — Textual-based terminal UI for the Cogito Agent.

Replaces the old argparse CLI with a full-screen interactive experience
inspired by Google's gemini-cli (React+Ink) TUI architecture.

Architecture:
- ``app.py`` — Textual ``App`` subclass, entry point, reactive state
- ``screens/chat_screen.py`` — Main chat layout (message list + composer + footer)
- ``widgets/`` — Message list, composer, input prompt, dialogs, footer
- ``themes/`` — Semantic color tokens, theme manager, built-in CSS themes
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid
from pathlib import Path

from textual.app import App
from textual.reactive import reactive

from cogito_agent.application import (
    ApprovalApplicationService,
    ChatApplicationService,
    InboxApplicationService,
    SessionApplicationService,
    WorkspaceApplicationService,
)
from cogito_agent.application.runtime_factory import build_runtime_kernel, default_workspace_path
from cogito_agent.storage import Database

if __name__ != "__main__":
    _logger = logging.getLogger(__name__)


class TUIState:
    """Central reactive UI state — mounted on the App as reactive attributes.

    Widgets access via ``self.app.tui_state.<attr>`` or ``watch_`` methods.
    """

    theme_name: str = "default-dark"
    dialogs_visible: bool = False
    streaming_active: bool = False

    # Dialog flags (matched by DialogManager priority chain)
    show_theme_dialog: bool = False
    show_settings_dialog: bool = False
    show_model_dialog: bool = False
    show_session_dialog: bool = False
    show_memory_dialog: bool = False
    show_auth_dialog: bool = False
    show_confirm_dialog: bool = False
    show_help_dialog: bool = False


class CogitoTUI(App):
    """Main Textual application for Cogito.

    Initialises all Application Services once and exposes them on ``self``.
    The TUI never accesses ``Database`` directly — all data flows through services.
    """

    CSS_PATH = None  # Will be set from theme manager

    # App-level CSS — force background to use theme surface color
    CSS = """
    Screen {
        background: $surface;
    }
    """

    # Reactive attributes for the TUI
    theme_name: reactive[str] = reactive("default-dark")
    dialogs_visible: reactive[bool] = reactive(False)
    streaming_active: reactive[bool] = reactive(False)

    def __init__(self, db_path: str = "") -> None:
        super().__init__()
        db_path = db_path or os.path.join(os.path.expanduser("~/.cogito"), "cogito.db")

        # ── Single Database instance — closed in on_exit ──
        self._db = Database(db_path)
        self._db.initialize()
        self._db.migrate()

        # ── Default workspace + session ──
        self._workspace_id = "default"
        self._session_id = str(uuid.uuid4())
        ws_path = default_workspace_path(self._workspace_id)
        Path(ws_path).mkdir(parents=True, exist_ok=True)

        # ── Application Services (the only way TUI touches data) ──
        from cogito_agent.autonomy import FeedbackStore, Outbox
        from cogito_agent.governance import AuditLogger
        from cogito_agent.memory.application import MemoryApplicationService
        from cogito_agent.storage.repositories import ApprovalRepository

        audit = AuditLogger(self._db)
        self.workspace_service = WorkspaceApplicationService(self._db, audit=audit)
        self.session_service = SessionApplicationService(self._db, audit=audit)
        self.memory_service = MemoryApplicationService(self._db, audit=audit)
        self.inbox_service = InboxApplicationService(
            Outbox(self._db), FeedbackStore(self._db, audit_logger=audit), audit,
        )
        self.approval_service = ApprovalApplicationService(
            ApprovalRepository(self._db), audit,
        )

        # ── Workspace + Session ──
        self.workspace_service.ensure_workspace(self._workspace_id, "default")
        self._session = self.session_service.create(
            self._workspace_id, "Cogito TUI", actor_id="tui",
        )
        self._session_id = str(self._session.get("id", self._session_id))

        # ── Runtime Kernel ──
        self._kernel = build_runtime_kernel(
            self._db, workspace_path=ws_path,
        )
        self.chat_service = ChatApplicationService(self._kernel)

        # ── TUI State ──
        self.tui_state = TUIState()

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def on_exit(self) -> None:
        self._db.close()

    async def on_mount(self) -> None:
        from .screens.chat_screen import ChatScreen
        from .themes.manager import ThemeManager

        # Register and activate theme
        ThemeManager.register_all(self)
        ThemeManager.set_active(self, "cogito-dark")

        self.push_screen(ChatScreen())

    # ── Dialog management ──

    def watch_dialogs_visible(self, visible: bool) -> None:
        """Reactive watcher — when dialogs become visible, push the active dialog."""
        from .widgets.dialog_manager import DialogManager

        dm = DialogManager(self)
        if visible:
            dialog_cls = dm.get_active_dialog_cls()
            if dialog_cls:
                self.push_screen(dialog_cls())
        elif not dm.has_active_flag():
            # Only pop dialog screens, not the main chat screen
            if len(self.screen_stack) > 1:
                screen = self.screen_stack[-1]
                from textual.screen import ModalScreen
                if isinstance(screen, ModalScreen):
                    self.pop_screen()


def run_tui(db_path: str = "") -> None:
    """Entry point for the TUI."""
    app = CogitoTUI(db_path=db_path)
    app.run()


def main() -> None:
    """CLI entry point for ``cogito-tui``."""
    parser = argparse.ArgumentParser(description="Cogito Agent Terminal UI")
    parser.add_argument(
        "--db-path",
        default=os.path.join(os.path.expanduser("~/.cogito"), "cogito.db"),
        help="Path to the SQLite database",
    )
    args = parser.parse_args()
    run_tui(db_path=args.db_path)


if __name__ == "__main__":
    main()
