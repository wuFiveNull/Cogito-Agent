from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class EventSource(StrEnum):
    cli = "cli"
    api = "api"
    scheduler = "scheduler"
    skill = "skill"
    webhook = "webhook"


class EventType(StrEnum):
    user_message = "user_message"
    tool_result = "tool_result"
    approval_result = "approval_result"
    resume = "resume"
    interrupt = "interrupt"


class RuntimeEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    session_id: str
    actor_id: str
    source: EventSource
    type: EventType
    payload: dict[str, object]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parent_trace_id: Optional[str] = None
