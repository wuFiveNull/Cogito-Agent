from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    """A delta of streamed assistant text.

    The consumer accumulates chunks and renders progressively (streaming
    response in the web UI, or buffered in the CLI).
    """

    text: str
    """Incremental text delta from the model."""


@dataclass(frozen=True)
class ToolCallChunk:
    """A tool invocation event during streaming.

    Emitted when the model starts or finishes a tool call, so the channel
    can show tool progress to the user.
    """

    tool_name: str
    """Name of the tool being called."""

    args_preview: str
    """Short human-readable preview of the arguments."""

    index: int = 0
    """Monotonic per-turn index for correlating start/finish."""

    finished: bool = False
    """True when this tool call has completed with a result."""


@dataclass(frozen=True)
class MessageStop:
    """The current assistant message segment is complete.

    ``final`` is True only for the terminal stop of the whole turn;
    an intermediate stop (text → tool call → more text) carries
    ``final=False``.
    """

    final: bool = False


StreamEvent = TextChunk | ToolCallChunk | MessageStop
"""Union type of all streaming events produced during turn processing."""
