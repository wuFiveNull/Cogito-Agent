"""Info/warning/error message renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Static

from . import factory as _factory

if TYPE_CHECKING:
    pass


@_factory.register("info")
class InfoMessage(Static):
    """Renders an informational system message."""

    DEFAULT_CSS = """
    InfoMessage {
        width: 100%;
        padding: 0 2;
        color: $text-disabled;
    }
    """

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        content = message.get("content", message.get("text", ""))
        self.update(f"  {content}")


@_factory.register("warning")
class WarningMessage(Static):
    """Renders a warning message."""

    DEFAULT_CSS = """
    WarningMessage {
        width: 100%;
        padding: 0 2;
        color: $warning;
    }
    """

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        content = message.get("content", message.get("text", ""))
        self.update(f"  ⚠ {content}")


@_factory.register("error")
class ErrorMessage(Static):
    """Renders an error message."""

    DEFAULT_CSS = """
    ErrorMessage {
        width: 100%;
        padding: 0 2;
        color: $error;
    }
    """

    def __init__(self, message: dict[str, Any]) -> None:
        super().__init__()
        content = message.get("content", message.get("text", ""))
        self.update(f"  ✗ {content}")
