"""Main chat screen — the primary TUI layout.

Mirrors gemini-cli's ``DefaultAppLayout``: a vertical split with:
- ``MessageList`` (grow) — virtualized message history
- ``Composer`` (fixed) — bottom input area
- ``Footer`` (fixed) — status bar

Phase 4: Kernel integration with streaming support.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.screen import Screen
from textual.worker import Worker, WorkerState, get_current_worker

from cogito_agent.shared import EventSource, EventType, RuntimeEvent

if TYPE_CHECKING:
    from cogito_agent.shared.stream_events import StreamEvent


class ChatScreen(Screen):
    """Main chat screen.

    Layout (vertical, top-to-bottom):
      MessageList  [grow]  — conversation history
      Composer     [auto]  — input area
      Footer       [1]     — status bar

    Stream events from RuntimeKernel.process_stream() are consumed
    by a threaded worker and dispatched to the UI.
    """

    DEFAULT_CSS = """
    ChatScreen {
        layout: vertical;
    }
    #message-list {
        height: 1fr;
        overflow-y: auto;
        background: $surface;
        border-bottom: solid $border;
    }
    #composer {
        height: auto;
        max-height: 6;
        background: $boost;
    }
    #footer {
        height: 1;
        background: $surface;
    }
    """

    def __init__(self) -> None:
        self._pending_assistant_id: str = ""
        self._streaming_finished: bool = False
        super().__init__()

    def compose(self) -> ComposeResult:
        from ..widgets.composer import Composer
        from ..widgets.footer import TuiFooter
        from ..widgets.message_list import MessageList
        yield MessageList(id="message-list")
        yield Composer(id="composer")
        yield TuiFooter(id="footer")

    def on_mount(self) -> None:
        app = self.app
        if hasattr(app, "theme_name"):
            self.watch(app, "theme_name", self._on_theme_change)

    def _on_theme_change(self, _theme_name: str) -> None:
        self.refresh()

    # ── Message submission ──

    async def on_composer_submit_message(self, message: Any) -> None:
        text = message.text.strip()
        if not text:
            return
        self._handle_submit(text)

    def _handle_submit(self, text: str) -> None:
        if text.startswith("/"):
            self._handle_command(text)
        else:
            self._handle_chat(text)

    # ── Chat (kernel streaming) ──

    def _handle_chat(self, text: str) -> None:
        """Submit a chat message to the kernel for streaming."""
        app = self.app
        app.tui_state.streaming_active = True  # type: ignore[attr-defined]

        # Add user message immediately
        self._add_message("user", text)

        # Add a placeholder assistant message that will stream
        mid = str(uuid.uuid4())
        self._pending_assistant_id = mid
        self._add_message("assistant", "", msg_id=mid)

        # Build the RuntimeEvent
        event = RuntimeEvent(
            workspace_id=app.workspace_id,
            session_id=app.session_id,
            actor_id="user",
            source=EventSource.cli,
            type=EventType.user_message,
            payload={"text": text},
        )

        # Run in the background via Textual worker
        self.run_worker(
            self._stream_kernel(event),
            name="kernel-stream",
            group="kernel",
            exit_on_error=False,
        )

    def _stream_kernel(self, event: RuntimeEvent):
        """Worker coroutine: consume process_stream generator.

        Runs in a Textual worker on the main thread — direct UI access is safe.
        """
        app = self.app
        worker = None
        try:
            worker = get_current_worker()
        except Exception:
            pass  # Outside worker context (e.g. tests)

        try:
            for stream_event in app.chat_service.process_stream(
                event,
                streaming_enabled=True,
            ):
                if worker and worker.is_cancelled:
                    break
                self._handle_stream_event(stream_event)
        except Exception as exc:
            self._add_message("error", f"Error: {exc}")
        finally:
            self._finish_streaming()

    def _handle_stream_event(self, event: StreamEvent) -> None:
        """Dispatch a single stream event (called from main thread)."""
        etype = event.type.value

        if etype == "delta":
            text_delta = event.data.get("delta", "")
            if text_delta:
                self._update_assistant_text(str(text_delta))

        elif etype == "final":
            full = event.data.get("content", event.data.get("text", ""))
            self._update_assistant_text(str(full))

        elif etype == "error":
            msg = event.data.get("message", str(event.data))
            self._add_message("error", f"Error: {msg}")

        elif etype == "tool_call_started":
            name = event.data.get("tool_name", event.data.get("name", "?"))
            self._add_message("tool", f"Tool: {name} (running...)")

        elif etype == "tool_call_completed":
            name = event.data.get("tool_name", event.data.get("name", "?"))
            status = event.data.get("status", "completed")
            self._add_message("tool", f"Tool: {name} ({status})")

        elif etype == "approval_required":
            app = self.app
            app.tui_state.show_confirm_dialog = True  # type: ignore[attr-defined]
            app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]

        elif etype == "metadata":
            pass  # Ignore

    def _update_assistant_text(self, text: str) -> None:
        """Append text to the in-progress assistant message."""
        msg_list = self.query_one("#message-list")
        for child in msg_list.children:
            mid = getattr(child, "message_id", "")
            if mid == self._pending_assistant_id:
                child.message["content"] = child.message.get("content", "") + text
                widget = child.query("AssistantMessage")
                if widget:
                    widget.first().update(
                        f"  AI: {child.message['content']}"
                    )
                else:
                    child.update(f"  AI: {child.message['content']}")
                break

    def _finish_streaming(self) -> None:
        """Clean up after streaming completes."""
        self._streaming_finished = True
        self._pending_assistant_id = ""
        app = self.app
        app.tui_state.streaming_active = False  # type: ignore[attr-defined]

    # ── Slash commands ──

    def _handle_command(self, text: str) -> None:
        parts = text[1:].split()
        cmd = parts[0].lower() if parts else ""

        dispatch = {
            "help": self._cmd_help,
            "theme": self._cmd_theme,
            "settings": self._cmd_settings,
            "model": self._cmd_model,
            "session": self._cmd_session,
            "memory": self._cmd_memory,
            "quit": self._cmd_quit,
            "clear": self._cmd_clear,
        }
        handler = dispatch.get(cmd, self._cmd_unknown)
        handler(text)

    def _cmd_help(self, _text: str) -> None:
        app = self.app
        app.tui_state.show_help_dialog = True  # type: ignore[attr-defined]
        app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]

    def _cmd_theme(self, _text: str) -> None:
        app = self.app
        app.tui_state.show_theme_dialog = True  # type: ignore[attr-defined]
        app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]

    def _cmd_settings(self, _text: str) -> None:
        app = self.app
        app.tui_state.show_settings_dialog = True  # type: ignore[attr-defined]
        app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]

    def _cmd_model(self, _text: str) -> None:
        app = self.app
        app.tui_state.show_model_dialog = True  # type: ignore[attr-defined]
        app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]

    def _cmd_session(self, _text: str) -> None:
        app = self.app
        app.tui_state.show_session_dialog = True  # type: ignore[attr-defined]
        app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]

    def _cmd_memory(self, text: str) -> None:
        app = self.app
        parts = text[1:].split()
        if len(parts) <= 1:
            app.tui_state.show_memory_dialog = True  # type: ignore[attr-defined]
            app.tui_state.dialogs_visible = True  # type: ignore[attr-defined]
            return
        sub = parts[1].lower()
        if sub == "list":
            memories = app.memory_service.list(app.workspace_id)  # type: ignore[attr-defined]
            self._add_message("info", f"Memories ({len(memories)}):")
            for m in memories:
                self._add_message("info", f"  [{m.get('type','')}] {m.get('text','')[:80]}")
        elif sub == "search" and len(parts) > 2:
            query = " ".join(parts[2:])
            results = app.memory_service.recall_search(query, app.workspace_id)  # type: ignore[attr-defined]
            self._add_message("info", f"Search results for: {query}")
            for r in results:
                self._add_message("info", f"  {r.get('text','')[:80]}")
        elif sub == "add" and len(parts) > 2:
            text_to_add = " ".join(parts[2:])
            app.memory_service.create_memory(  # type: ignore[attr-defined]
                app.workspace_id, text_to_add, actor_id="tui",
            )
            self._add_message("info", f"Memory saved: {text_to_add[:80]}")

    def _cmd_quit(self, _text: str) -> None:
        self.app.exit()

    def _cmd_clear(self, _text: str) -> None:
        msg_list = self.query_one("#message-list")
        msg_list.remove_children()  # type: ignore[attr-defined]

    def _cmd_unknown(self, text: str) -> None:
        self._add_message("error", f"Unknown command: {text}")

    # ── Helper ──

    def _add_message(
        self,
        msg_type: str,
        content: str,
        msg_id: str = "",
    ) -> None:
        """Append a message widget to the message list."""
        msg = {
            "id": msg_id or str(uuid.uuid4()),
            "type": msg_type,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        msg_list = self.query_one("#message-list")
        from ..widgets.message_item import MessageItem
        msg_list.mount(MessageItem(msg))  # type: ignore[attr-defined]
        msg_list.scroll_end(animate=False)  # type: ignore[attr-defined]

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker lifecycle for streaming."""
        if (
            event.worker.name == "kernel-stream"
            and event.state == WorkerState.ERROR
            and not self._streaming_finished
        ):
            self._add_message("error", "Kernel worker terminated unexpectedly")
            self._finish_streaming()


# Make Any available for the on_composer_submit_message signature
