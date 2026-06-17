from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class DecisionAction(StrEnum):
    push = "push"
    skip = "skip"
    defer = "defer"
    require_approval = "require_approval"


class NotificationDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    action: DecisionAction
    reason_code: str = ""
    reason: str = ""
    cost_score: float = 0.0
    priority_score: float = 0.0
    dedup_hit: bool = False
    quiet_hours_hit: bool = False
    quota_hit: bool = False
    requires_approval: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_id: str = ""
    workspace_id: str = "*"
    user_id: str = ""
