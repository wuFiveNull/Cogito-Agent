"""In-memory message buffer for the chat conversation.

Replaces gemini-cli's ``useHistory`` hook + ``UIState.history`` pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


class ChatStore:
    """Append-only buffer of messages for the current session.

    Messages are plain dicts with schema:
      ``{"id": str, "type": str, "content": str, "timestamp": str, ...}``
    """

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    @property
    def last_message(self) -> dict[str, Any] | None:
        return self._messages[-1] if self._messages else None

    def append(self, msg: dict[str, Any]) -> None:
        """Append a message, assigning an id and timestamp if missing."""
        if "id" not in msg:
            msg["id"] = str(uuid.uuid4())
        if "timestamp" not in msg:
            msg["timestamp"] = datetime.now(UTC).isoformat()
        self._messages.append(dict(msg))

    def update_last(self, **fields: Any) -> None:
        """Update fields on the most recent message (used during streaming)."""
        if self._messages:
            self._messages[-1].update(fields)

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)
