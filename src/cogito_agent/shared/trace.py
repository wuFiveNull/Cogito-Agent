from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SpanKind(StrEnum):
    runtime = "runtime"
    context = "context"
    model = "model"
    tool = "tool"
    policy = "policy"
    approval = "approval"
    memory = "memory"
    storage = "storage"
    result = "result"
    scheduler = "scheduler"
    autonomous = "autonomous"


class Span(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    parent_span_id: str | None = None
    name: str
    kind: SpanKind
    status: str = "running"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    input_summary: str = ""
    output_summary: str = ""
    error: str | None = None
    metadata_json: str = "{}"


class Trace(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    session_id: str | None = None
    root_event_id: str
    status: str = "running"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    spans: list[Span] = []
