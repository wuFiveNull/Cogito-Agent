from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    """Standardized inbound message from any channel (CLI, Web, ACP, etc.).

    This is the canonical input type for the message queue — all frontends
    produce InboundMessage, and AgentLoop consumes it.
    """

    channel: str
    """Source channel identifier, e.g. "cli", "web", "acp", "telegram"."""

    session_id: str
    """Conversation session ID."""

    workspace_id: str
    """Workspace / project scope."""

    content: str
    """Text content of the message. Empty for purely multi-modal messages."""

    media: list[dict[str, Any]] | None = None
    """Multi-modal media parts (images, files, etc.). Each is a dict with
    ``type`` ("image", "file", "audio") and ``data`` / ``uri``."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary transport metadata (sender, timestamp, extra flags)."""


@dataclass
class OutboundMessage:
    """Standardized outbound message produced by AgentLoop.

    Carries the final response content and any streaming events that were
    produced during processing. Channels consume OutboundMessage and deliver
    it to the user.
    """

    channel: str
    """Target channel identifier (echoes the inbound channel)."""

    session_id: str
    """Conversation session ID."""

    workspace_id: str
    """Workspace / project scope."""

    content: str
    """Final assistant response text."""

    thinking: str | None = None
    """Model reasoning / thinking block, if available."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Response metadata (trace_id, token counts, model name, latency)."""
