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


# ── App Config ────────────────────────────────────────────────────────────


class AppConfig(BaseModel):
    name: str = "Cogito-Agent"
    data_dir: str = "~/.cogito/data"
    workspace_root: str = "~/.cogito/workspace"
    default_entrypoint: str = "cli"


# ── Model Configuration ────────────────────────────────────────────────────


class ProviderConnectionSettings(BaseModel):
    base_url: str | None = None
    api_key_ref: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 60
    max_retries: int = 2


class ModelCandidateSettings(BaseModel):
    id: str = ""
    provider: str = ""
    base_url: str | None = None
    api_key_ref: str | None = None
    api_key: str | None = None
    model: str = ""
    connection_ref: str | None = None
    capabilities: list[str] = Field(default_factory=lambda: ["chat"])
    roles: list[str] = Field(default_factory=lambda: ["chat"])
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_formats: list[str] = Field(default_factory=list)
    context_window: int = 32768
    quality_score: float = 0.5
    expected_latency_ms: int = 1000
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    priority: int = 100
    enabled: bool = True

    def to_candidate_id(self) -> str:
        return self.id or f"{self.provider}:{self.model}"


class ModelRouteSettings(BaseModel):
    required_capabilities: list[str] = Field(default_factory=lambda: ["chat"])
    required_input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    required_output_formats: list[str] = Field(default_factory=list)
    role: str = ""
    preferred_candidates: list[str] = Field(default_factory=list)
    strict_preferred: bool = False
    fallback_strategy: str = "ordered"  # "ordered" or "none"


class ModelsSettings(BaseModel):
    provider: str = "mock"
    base_url: str | None = None
    api_key_ref: str | None = None
    model: str = "mock-chat"
    timeout_seconds: int = 60
    max_retries: int = 2
    candidates: list[ModelCandidateSettings] = Field(default_factory=list)
    routes: dict[str, ModelRouteSettings] = Field(default_factory=dict)


# ── Runtime ───────────────────────────────────────────────────────────────


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


# ── Top-Level Config ──────────────────────────────────────────────────────


class CogitoConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    model: ModelsSettings = Field(default_factory=ModelsSettings)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    trace: TraceConfig = Field(default_factory=TraceConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    capabilities: dict[str, list[str]] = Field(default_factory=lambda: {"enabled": list[str]()})
    security: SecurityConfig = Field(default_factory=SecurityConfig)


# ── Policy Config ─────────────────────────────────────────────────────────


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


# ── Loading ───────────────────────────────────────────────────────────────


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


# ── Build RoutedModelAdapter ──────────────────────────────────────────────


def build_multimodel_adapter(
    config: CogitoConfig | None = None,
) -> Any | None:
    """Build a RoutedModelAdapter from multi-candidate YAML config.

    Reads model.candidates from the config and creates a router with
    all enabled candidates. Falls back to single-model config if no
    candidates are defined.

    Returns a RoutedModelAdapter or None (mock mode).
    """
    if config is None:
        config = load_config()

    cfg = config.model

    if cfg.candidates:
        adapters: dict[str, ModelAdapter] = {}
        candidates: list[ModelCandidate] = []

        from cogito_agent.models import ModelAdapter, ModelCandidate, ModelRouter, RoutedModelAdapter
        from cogito_agent.models.openai_adapter import OpenAICompatibleAdapter

        for cand_cfg in cfg.candidates:
            if not cand_cfg.enabled:
                continue
            if cand_cfg.provider == "mock":
                continue

            api_key = cand_cfg.api_key or ""
            if cand_cfg.api_key_ref:
                api_key = os.environ.get(cand_cfg.api_key_ref, "") or api_key

            adapter = OpenAICompatibleAdapter(
                api_key=api_key or "",
                base_url=cand_cfg.base_url or "",
                model=cand_cfg.model,
                timeout_sec=cfg.timeout_seconds,
            )

            candidate = ModelCandidate(
                candidate_id=cand_cfg.id,
                provider=cand_cfg.provider,
                model=adapter.model,
                capabilities=set(cand_cfg.capabilities) if cand_cfg.capabilities else {"chat"},
                roles=frozenset(cand_cfg.roles) if cand_cfg.roles else frozenset({"chat"}),
                input_modalities=(
                    frozenset(cand_cfg.input_modalities)
                    if cand_cfg.input_modalities else frozenset({"text"})
                ),
                output_formats=frozenset(cand_cfg.output_formats) if cand_cfg.output_formats else frozenset(),
                context_window=cand_cfg.context_window,
                quality_score=cand_cfg.quality_score,
                expected_latency_ms=cand_cfg.expected_latency_ms,
                input_cost_per_million=cand_cfg.input_cost_per_million,
                output_cost_per_million=cand_cfg.output_cost_per_million,
                priority=cand_cfg.priority,
                enabled=True,
            )
            adapters[candidate.id] = adapter
            candidates.append(candidate)

        if not candidates:
            return None

        router = ModelRouter(candidates)

        def _resolve(c: ModelCandidate) -> ModelAdapter:
            return adapters[c.id]

        return RoutedModelAdapter(router, _resolve)

    if cfg.provider == "mock":
        return None

    from cogito_agent.models import ModelCandidate, ModelRouter, RoutedModelAdapter
    from cogito_agent.models.openai_adapter import OpenAICompatibleAdapter

    api_key = cfg.api_key_ref or ""
    if api_key:
        api_key = os.environ.get(api_key, "")
    adapter = OpenAICompatibleAdapter(
        api_key=api_key or "",
        base_url=cfg.base_url or "",
        model=cfg.model,
        timeout_sec=cfg.timeout_seconds,
    )
    candidate = ModelCandidate(
        provider=cfg.provider,
        model=adapter.model,
        capabilities={"chat", "tools"},
        context_window=32_768,
    )
    router = ModelRouter([candidate])
    return RoutedModelAdapter(router, lambda _c: adapter)


__all__ = [
    "AppConfig",
    "ModelsSettings",
    "ModelCandidateSettings",
    "ModelRouteSettings",
    "ProviderConnectionSettings",
    "RuntimeConfig",
    "MemoryConfig",
    "TraceConfig",
    "AuditConfig",
    "SecurityConfig",
    "CogitoConfig",
    "PolicyConfig",
    "load_config",
    "load_policy_config",
    "build_multimodel_adapter",
]
