from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parent_trace_id: str | None = None
