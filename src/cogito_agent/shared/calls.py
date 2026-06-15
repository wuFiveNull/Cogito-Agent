from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    span_id: str
    capability_name: str
    input_summary: str = ""
    decision: str = ""
    approval_id: str | None = None
    status: str = ""
    output_summary: str = ""
    latency_ms: int = 0
    error: str | None = None


class ModelCall(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    span_id: str
    provider: str = ""
    model: str = ""
    input_token_count: int = 0
    output_token_count: int = 0
    prompt_summary: str = ""
    response_summary: str = ""
    latency_ms: int = 0
    stop_reason: str = ""
    error: str | None = None
