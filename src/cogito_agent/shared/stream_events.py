from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel


class StreamEventType(StrEnum):
    metadata = "metadata"
    delta = "delta"
    final = "final"
    error = "error"
    approval_required = "approval_required"
    tool_call_started = "tool_call_started"
    tool_call_completed = "tool_call_completed"


class StreamEvent(BaseModel):
    type: StreamEventType
    data: dict[str, object] = {}
    request_id: str = ""
    trace_id: str = ""

    def to_sse(self) -> str:
        return f"event: {self.type.value}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"
