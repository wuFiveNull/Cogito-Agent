from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SkillRiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class StepKind(StrEnum):
    capability = "capability"
    llm = "llm"
    transform = "transform"


class OnError(StrEnum):
    stop = "stop"
    skip = "skip"
    rollback = "rollback"


class SkillStep(BaseModel):
    id: str
    name: str
    kind: StepKind = StepKind.capability
    uses_capability: str = ""
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)
    on_error: OnError = OnError.stop
    trace_required: bool = True
    prompt: str = ""


class SkillManifest(BaseModel):
    name: str
    version: str
    description: str = ""
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    steps: list[SkillStep] = Field(default_factory=list)
    permissions: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: SkillRiskLevel = SkillRiskLevel.medium
    rollback: list[dict[str, Any]] = Field(default_factory=list)
    owner: str = "built-in"
