from __future__ import annotations

import os
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _expand_path(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


DEFAULT_CONFIG_PATHS: list[str] = [
    "configs/default.yaml",
    os.path.join(_expand_path("~/.cogito"), "config.yaml"),
]


class AppConfig(BaseModel):
    name: str = "Cogito-Agent"
    data_dir: str = "~/.cogito/data"
    workspace_root: str = "~/.cogito/workspace"
    default_entrypoint: str = "cli"


class ModelConfig(BaseModel):
    provider: str = "mock"
    base_url: str | None = None
    api_key_ref: str | None = None
    model: str = "mock-chat"
    timeout_seconds: int = 60
    max_retries: int = 2


class RuntimeConfig(BaseModel):
    max_turn_steps: int = 12
    max_model_calls: int = 4
    max_tool_calls: int = 5
    max_context_tokens: int = 24000
    max_output_tokens: int = 4000
    max_cost_usd_per_turn: float = 0.20
    turn_timeout_seconds: int = 120


class MemoryRetrievalConfig(BaseModel):
    bm25_top_k: int = 8
    vector_top_k: int = 0
    final_top_k: int = 6


class MemoryConfig(BaseModel):
    enabled: bool = True
    write_mode: str = "candidate_requires_approval"
    retrieval: MemoryRetrievalConfig = Field(default_factory=MemoryRetrievalConfig)


class TraceConfig(BaseModel):
    enabled: bool = True
    payload_mode: str = "metadata_plus_redacted"
    retention_days: int = 30


class AuditConfig(BaseModel):
    enabled: bool = True


class SecurityConfig(BaseModel):
    deny_shell: bool = True
    deny_workspace_escape: bool = True
    external_content_trust: str = "untrusted"


class CogitoConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    capabilities: dict[str, list[str]] = Field(default_factory=lambda: {"enabled": list[str]()})
    security: SecurityConfig = Field(default_factory=SecurityConfig)


class PolicyRuleConfig(BaseModel):
    id: str
    actor: list[str]
    capability: list[str]
    resource: dict[str, str]
    operation: list[str]
    decision: str


class PolicyConfig(BaseModel):
    default_decision: str = "deny"
    rules: list[PolicyRuleConfig] = Field(default_factory=list)


def _find_config(paths: list[str]) -> str | None:
    for p in paths:
        expanded = _expand_path(p)
        if os.path.isfile(expanded):
            return expanded
    return None


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(
    paths: list[str] | None = None,
) -> CogitoConfig:
    resolved = paths or list(DEFAULT_CONFIG_PATHS)
    cfg_path = _find_config(resolved)
    if cfg_path is None:
        return CogitoConfig()
    raw = _load_yaml(cfg_path)
    return CogitoConfig(**raw)


def load_policy_config(
    path: str | None = None,
) -> PolicyConfig:
    if path is None:
        for p in ["configs/policy.yaml"]:
            expanded = _expand_path(p)
            if os.path.isfile(expanded):
                path = expanded
                break
    if path is None or not os.path.isfile(path):
        return PolicyConfig()
    raw = _load_yaml(path)
    return PolicyConfig(**raw)
