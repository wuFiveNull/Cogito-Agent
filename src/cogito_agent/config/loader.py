from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _expand_path(path: str) -> str:
    return os.path.expanduser(os.path.expandvars(path))


def _bool_env(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _int_env(val: str | None, default: int) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ── Config models ──────────────────────────────────────────────────────────


class AppSettings(BaseModel):
    data_dir: str = "~/.cogito/data"
    workspace_root: str = "~/.cogito/workspace"


class ModelSettings(BaseModel):
    provider: str = "mock"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    api_key_env: str = "MODEL_API_KEY"
    secret_ref: str = ""
    timeout_seconds: int = 60
    max_retries: int = 2
    streaming_enabled: bool = True


class QuietHoursSettings(BaseModel):
    enabled: bool = True
    start: str = "22:00"
    end: str = "08:00"
    timezone: str = "local"


class NotificationSettings(BaseModel):
    daily_quota: int = 5
    hourly_quota: int = 2
    urgent_bypass_quiet_hours: bool = True
    urgent_bypass_quota: bool = True


class DedupSettings(BaseModel):
    window_minutes: int = 120


class FeedbackSettings(BaseModel):
    enabled: bool = True


class AutonomySettings(BaseModel):
    enabled: bool = True
    quiet_hours: QuietHoursSettings = Field(default_factory=QuietHoursSettings)
    notification: NotificationSettings = Field(default_factory=NotificationSettings)
    dedup: DedupSettings = Field(default_factory=DedupSettings)
    feedback: FeedbackSettings = Field(default_factory=FeedbackSettings)


class SecretsSettings(BaseModel):
    backend: str = "dev_sqlite"
    service_name: str = "cogito-agent"
    local_path: str = ""


class StorageSettings(BaseModel):
    db_path: str = "~/.cogito/cogito.db"
    auto_vacuum: bool = False
    maintenance_interval_hours: int = 24
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_retention_count: int = 7
    backup_dir: str = "~/.cogito/backups"


class LoggingSettings(BaseModel):
    level: str = "INFO"
    format: str = "json"
    max_size: int = 10 * 1024 * 1024
    backup_count: int = 5


class SecuritySettings(BaseModel):
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ])
    max_request_size: int = 10 * 1024 * 1024
    csrf_enabled: bool = True


class RuntimeSettings(BaseModel):
    max_turn_steps: int = 12
    max_model_calls: int = 4
    max_tool_calls: int = 5
    max_context_tokens: int = 24000
    max_output_tokens: int = 4000
    max_cost_usd_per_turn: float = 0.20
    turn_timeout_seconds: int = 120


class MemoryRetrievalSettings(BaseModel):
    bm25_top_k: int = 8
    vector_top_k: int = 0
    final_top_k: int = 6


class MemorySettings(BaseModel):
    enabled: bool = True
    write_mode: str = "candidate_requires_approval"
    retrieval: MemoryRetrievalSettings = Field(default_factory=MemoryRetrievalSettings)


class CogitoConfig(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    model: ModelSettings = Field(default_factory=ModelSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)
    autonomy: AutonomySettings = Field(default_factory=AutonomySettings)


# ── Env var mapping ────────────────────────────────────────────────────────

ENV_MAP: dict[str, tuple[str, type]] = {
    "COGITO_DB_PATH": ("storage.db_path", str),
    "COGITO_LOG_LEVEL": ("logging.level", str),
    "COGITO_LOG_FORMAT": ("logging.format", str),
    "COGITO_LOG_MAX_SIZE": ("logging.max_size", int),
    "COGITO_LOG_BACKUP_COUNT": ("logging.backup_count", int),
    "COGITO_CORS_ORIGINS": ("security.cors_origins", str),
    "COGITO_MAX_REQUEST_SIZE": ("security.max_request_size", int),
    "COGITO_CSRF_ENABLED": ("security.csrf_enabled", bool),
    "COGITO_API_KEY": ("api_key", str),
}


def _get_in_dict(d: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    cur = d
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p, {})
        else:
            return None
    return cur if cur != {} else None


def _set_in_dict(d: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        if p not in cur:
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _load_toml_file(path: str) -> dict[str, Any]:
    try:
        import tomllib as _toml_mod
    except ImportError:
        try:
            import tomli as _toml_mod  # type: ignore[no-redef]
        except ImportError:
            return {}
    try:
        with open(path, "rb") as f:
            return _toml_mod.load(f)
    except (FileNotFoundError, PermissionError, ValueError):
        return {}


def load_toml_config(path: str | None = None) -> dict[str, Any]:
    if path is None:
        path = os.path.join(_expand_path("~/.cogito"), "config.toml")
    return _load_toml_file(path)


def _load_env_overrides() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for env_key, (config_path, _) in ENV_MAP.items():
        val = os.environ.get(env_key)
        if val is not None:
            _set_in_dict(result, config_path, val)
    return result


def _load_env_as_flat() -> dict[str, str]:
    result: dict[str, str] = {}
    for env_key, (config_path, _) in ENV_MAP.items():
        val = os.environ.get(env_key)
        if val is not None:
            result[config_path] = val
    return result


def load_config(
    config_path: str | None = None,
    cli_overrides: dict[str, str] | None = None,
) -> CogitoConfig:
    raw: dict[str, Any] = {}

    # 1. Defaults are built into Pydantic model constructors

    # 2. Config file (TOML preferred, YAML/JSON fallback)
    if config_path is None:
        config_path = os.path.join(_expand_path("~/.cogito"), "config.toml")

    # Try TOML first
    toml_data = load_toml_config(config_path)
    raw = _deep_merge(raw, toml_data)

    # Also try legacy YAML config for backward compat
    yaml_path = os.path.join(_expand_path("~/.cogito"), "config.yaml")
    if os.path.isfile(yaml_path):
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
            raw = _deep_merge(raw, yaml_data)
        except Exception:
            pass

    # Also try legacy JSON config for backward compat
    json_path = os.path.join(_expand_path("~/.cogito"), "config.json")
    if os.path.isfile(json_path):
        try:
            import json as _json
            with open(json_path, encoding="utf-8") as f:
                json_data = _json.load(f) or {}
            raw = _deep_merge(raw, json_data)
        except Exception:
            pass

    # 3. Environment variables override config file
    env_overrides = _load_env_overrides()
    raw = _deep_merge(raw, env_overrides)

    # 4. CLI overrides have highest priority
    if cli_overrides:
        for key, value in cli_overrides.items():
            _set_in_dict(raw, key, value)

    return CogitoConfig(**raw)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """Convenience wrapper that lazily loads config and provides dot-access."""

    _instance: CogitoConfig | None = None

    @classmethod
    def get(cls) -> CogitoConfig:
        if cls._instance is None:
            cls._instance = load_config()
        return cls._instance

    @classmethod
    def reload(cls, config_path: str | None = None) -> CogitoConfig:
        cls._instance = load_config(config_path=config_path)
        return cls._instance


DEFAULT_CONFIG_TOML = """# Cogito-Agent local configuration
# Precedence: CLI flags > environment variables > this file > defaults.

[app]
data_dir = "~/.cogito/data"
workspace_root = "~/.cogito/workspace"

[model]
provider = "mock"
base_url = ""
model = ""
api_key = ""
api_key_env = "MODEL_API_KEY"
secret_ref = ""
timeout_seconds = 60
max_retries = 2
streaming_enabled = true

[storage]
db_path = "~/.cogito/cogito.db"
auto_vacuum = false
maintenance_interval_hours = 24
backup_enabled = true
backup_interval_hours = 24
backup_retention_count = 7
backup_dir = "~/.cogito/backups"

[logging]
level = "INFO"
format = "json"
max_size = 10485760
backup_count = 5

[security]
cors_origins = ["http://localhost:8000", "http://127.0.0.1:8000"]
max_request_size = 10485760
csrf_enabled = true

[secrets]
backend = "dev_sqlite"
service_name = "cogito-agent"
local_path = ""

[autonomy]
enabled = true

[autonomy.quiet_hours]
enabled = true
start = "22:00"
end = "08:00"
timezone = "local"

[autonomy.notification]
daily_quota = 5
hourly_quota = 2
urgent_bypass_quiet_hours = true
urgent_bypass_quota = true
"""


def initialize_config(path: str | None = None, *, force: bool = False) -> str:
    """Create a validated default TOML configuration and return its path."""
    target = Path(path or _expand_path("~/.cogito/config.toml"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        raise FileExistsError(f"Config already exists: {target}")
    target.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
    # Refuse to leave an invalid generated configuration behind unnoticed.
    CogitoConfig(**load_toml_config(str(target)))
    return str(target)
