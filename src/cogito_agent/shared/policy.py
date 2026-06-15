from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DecisionType(StrEnum):
    allow = "allow"
    allow_with_audit = "allow_with_audit"
    require_approval = "require_approval"
    deny = "deny"
    escalate = "escalate"


class PolicyRequest(BaseModel):
    actor_id: str
    capability_name: str
    resource: str
    operation: str
    context: str


class PolicyDecision(BaseModel):
    decision: DecisionType
    reason: str = ""
    approval_id: str | None = None
