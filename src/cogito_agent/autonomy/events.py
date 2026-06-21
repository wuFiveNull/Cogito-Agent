from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AutonomySourceType(StrEnum):
    scheduler = "scheduler"
    drift = "drift"
    webhook = "webhook"
    memory = "memory"
    manual = "manual"
    system = "system"


class PriorityLevel(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class AutonomyChannel(StrEnum):
    alert = "alert"
    content = "content"
    context = "context"


class AutonomyEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = "system"
    source_type: AutonomySourceType = AutonomySourceType.system
    workspace_id: str = "*"
    user_id: str = ""
    title: str
    body: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_time: datetime | None = None
    priority: PriorityLevel = PriorityLevel.normal
    channel: AutonomyChannel = AutonomyChannel.content
    category: str = ""
    expires_at: datetime | None = None
    evidence: list[dict[str, str]] = Field(default_factory=list)
    ack_token: str = ""
    dedup_key: str = ""
    quiet_hours_override: bool = False
    metadata: dict[str, str] = {}
    trace_id: str = ""

    def build_dedup_key(self) -> str:
        if self.dedup_key:
            return self.dedup_key
        import hashlib

        raw = f"{self.source}|{self.title}|{self.category}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now or datetime.now(UTC)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= current
