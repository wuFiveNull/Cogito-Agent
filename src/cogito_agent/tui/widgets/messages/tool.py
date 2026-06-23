"""Tool message renderer — ``item.type == "tool_group"``.

Shows collapsible tool calls (expand/collapse on click).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from . import factory as _factory

if TYPE_CHECKING:
    pass


@_factory.register("tool")
class ToolMessage(Static):
    """Renders a tool call/results block."""

    DEFAULT_CSS = """
    ToolMessage {
        width: 100%;
        padding: 0 2;
        color: $text-disabled;
    }
    """

    _collapsed: bool = True

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        self._collapsed = True
        self.message = message
        self.update(self._render_tool())

    def _render_tool(self) -> str:
        tool_name = self.message.get("tool_name", self.message.get("name", "tool"))
        status = self.message.get("status", "running")
        icon = "⏳" if status == "running" else ("✓" if status == "success" else "✗")
        prefix = "  "
        result = f"{prefix}{icon} {tool_name} ({status})"
        if not self._collapsed:
            output = self.message.get("content", self.message.get("output", ""))
            if output:
                result += f"\n{prefix}  {output}"
        return result

    def on_click(self) -> None:
        self._collapsed = not self._collapsed
        self.update(self._render_tool())
