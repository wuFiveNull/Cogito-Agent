from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class CapabilityType(StrEnum):
    tool = "tool"
    mcp_server = "mcp_server"
    plugin = "plugin"
    skill = "skill"
    subagent = "subagent"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Permission(BaseModel):
    resource: str
    operations: list[str]


class CapabilityManifest(BaseModel):
    name: str
    version: str
    type: CapabilityType
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    permissions: list[Permission]
    risk_level: RiskLevel
    allowed_contexts: list[str]
    approval_required: bool
    audit_required: bool
    idempotent: bool
