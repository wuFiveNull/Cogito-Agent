from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    """A single item in the context window.

    Carries metadata about its origin, quality scores, and why it was
    included or excluded.  This is a pure data type shared across the
    context engine, runtime, and storage layers.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str
    source_id: str
    text: str
    rank: int = 0
    token_estimate: int = 0
    included: bool = True
    reason: str = ""
    role: str = ""
    tool_call_id: str = ""
    freshness_score: float = 0.5
    trust_score: float = 0.5
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    stable_ref: str = ""
    exclusion_reason: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.stable_ref:
            self.stable_ref = (
                f"{self.source_type}:{self.source_id}"
                if self.source_id
                else f"{self.source_type}:{self.id}"
            )
