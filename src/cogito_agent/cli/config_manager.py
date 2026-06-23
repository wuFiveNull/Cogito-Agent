from __future__ import annotations

import json
import os
from pathlib import Path

from cogito_agent.models import (
    ModelAdapter,
    ModelCandidate,
    ModelRouter,
    RoutedModelAdapter,
    get_adapter,
    list_providers,
)
from cogito_agent.models.registry import get_provider_config
from cogito_agent.security import (
    KeychainSecretProvider,
    LocalSecretsProvider,
    SecretProvider,
    get_provider_from_config,
)

CONFIG_DIR = os.path.expanduser("~/.cogito")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG: dict[str, str] = {
    "model.provider": "mock",
    "model.base_url": "",
    "model.model": "",
    "model.api_key": "",
    "model.api_key_env": "MODEL_API_KEY",
    "model.secret_ref": "",
    "model.timeout_seconds": "60",
    "model.max_retries": "2",
    "model.streaming_enabled": "true",
    "secrets.backend": "local",
    "secrets.service_name": "cogito-agent",
    "secrets.local_path": "",
    "autonomy.enabled": "true",
    "autonomy.quiet_hours.enabled": "true",
    "autonomy.quiet_hours.start": "22:00",
    "autonomy.quiet_hours.end": "08:00",
    "autonomy.quiet_hours.timezone": "local",
    "autonomy.notification.daily_quota": "5",
    "autonomy.notification.hourly_quota": "2",
    "autonomy.notification.urgent_bypass_quiet_hours": "true",
    "autonomy.notification.urgent_bypass_quota": "true",
    "autonomy.dedup.window_minutes": "120",
    "autonomy.feedback.enabled": "true",
}

KEYS = tuple(DEFAULT_CONFIG.keys())


def _ensure_dir() -> None:
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)


def _load_raw() -> dict[str, str]:
    _ensure_dir()
    if not os.path.isfile(CONFIG_PATH):
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)
        result = dict(DEFAULT_CONFIG)
        result.update({k: v for k, v in data.items() if k in KEYS})
        return result
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def _save_raw(data: dict[str, str]) -> None:
    _ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_config() -> dict[str, str]:
    return _load_raw()


def get_config_key(key: str) -> str:
    cfg = _load_raw()
    return cfg.get(key, DEFAULT_CONFIG.get(key, ""))


def set_config_key(key: str, value: str) -> None:
    if key not in KEYS:
        keys_str = ", ".join(KEYS)
        raise ValueError(f"Unknown config key: {key}. Valid keys: {keys_str}")
    cfg = _load_raw()
    cfg[key] = value
    _save_raw(cfg)


def _resolve_api_key(cfg: dict[str, str], secret_provider: SecretProvider | None = None) -> str:
    """Resolve API key from secret_ref, config value, or environment."""
    secret_ref = cfg.get("model.secret_ref", "")
    if secret_ref:
        try:
            provider = secret_provider or get_provider_from_config(cfg)
            sv = provider.get_secret(secret_ref)
            if sv is not None:
                return sv.value
        except Exception:
            pass
    configured_key = cfg.get("model.api_key", "")
    if configured_key:
        return configured_key
    api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
    return os.environ.get(api_key_env, "")


def build_model_adapter_from_config(
    secret_provider: SecretProvider | None = None,
) -> ModelAdapter | None:
    cfg = _load_raw()
    provider = cfg.get("model.provider", "mock")
    if provider == "mock":
        return None
    api_key = _resolve_api_key(cfg, secret_provider)
    timeout = int(cfg.get("model.timeout_seconds", "60"))
    adapter = get_adapter(
        provider=provider,
        model=cfg.get("model.model", ""),
        api_key=api_key,
        base_url=cfg.get("model.base_url", ""),
        timeout_sec=timeout,
    )
    candidate = ModelCandidate(
        provider=provider,
        model=str(getattr(adapter, "model", cfg.get("model.model", ""))),
        capabilities={"chat", "tools"},
        context_window=32_768,
    )
    router = ModelRouter([candidate])
    return RoutedModelAdapter(router, lambda _candidate: adapter)


def doctor() -> list[dict[str, str]]:
    cfg = _load_raw()
    results: list[dict[str, str]] = []

    provider = cfg.get("model.provider", "mock")
    providers = list_providers()
    if provider == "mock":
        results.append(
            {
                "check": "provider",
                "status": "ok",
                "detail": "mock (no API needed)",
            }
        )
    elif provider in providers:
        results.append(
            {
                "check": "provider",
                "status": "ok",
                "detail": f"provider '{provider}' registered",
            }
        )
    else:
        known = ", ".join(providers)
        results.append(
            {
                "check": "provider",
                "status": "warn",
                "detail": f"provider '{provider}' not in known list ({known})",
            }
        )

    base_url = cfg.get("model.base_url", "")
    if provider != "mock" and not base_url:
        pcfg = get_provider_config(provider)
        if pcfg and pcfg.base_url:
            results.append(
                {
                    "check": "base_url",
                    "status": "ok",
                    "detail": f"using default: {pcfg.base_url}",
                }
            )
        else:
            results.append(
                {
                    "check": "base_url",
                    "status": "warn",
                    "detail": "not set, will use OpenAI default",
                }
            )
    elif provider != "mock":
        results.append(
            {
                "check": "base_url",
                "status": "ok",
                "detail": base_url,
            }
        )

    model_name = cfg.get("model.model", "")
    if provider != "mock" and not model_name:
        pcfg = get_provider_config(provider)
        if pcfg and pcfg.default_model:
            results.append(
                {
                    "check": "model",
                    "status": "ok",
                    "detail": f"using default: {pcfg.default_model}",
                }
            )
        else:
            results.append(
                {
                    "check": "model",
                    "status": "warn",
                    "detail": "not set, will use env MODEL_NAME or gpt-4o-mini",
                }
            )
    elif provider != "mock":
        results.append(
            {
                "check": "model",
                "status": "ok",
                "detail": model_name,
            }
        )

    secret_ref = cfg.get("model.secret_ref", "")
    if provider != "mock" and secret_ref:
        try:
            secret_store: SecretProvider = LocalSecretsProvider()
            sv = secret_store.get_secret(secret_ref)
            if sv is not None:
                results.append(
                    {
                        "check": "secret_ref",
                        "status": "ok",
                        "detail": f"secret_ref '{secret_ref}' available",
                    }
                )
            else:
                results.append(
                    {
                        "check": "secret_ref",
                        "status": "warn",
                        "detail": f"secret_ref '{secret_ref}' configured but not found",
                    }
                )
        except Exception:
            results.append(
                {
                    "check": "secret_ref",
                    "status": "warn",
                    "detail": f"secret_ref '{secret_ref}' error resolving",
                }
            )
    elif provider != "mock" and cfg.get("model.api_key", ""):
        results.append(
            {
                "check": "model.api_key",
                "status": "ok",
                "detail": "configured in file (redacted)",
            }
        )
    elif provider != "mock":
        api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
        val = os.environ.get(api_key_env) if api_key_env else None
        if val:
            results.append(
                {
                    "check": "api_key_env",
                    "status": "ok",
                    "detail": f"${api_key_env} is set (legacy, prefer secret_ref)",
                }
            )
        else:
            results.append(
                {
                    "check": "api_key_env",
                    "status": "warn",
                    "detail": f"${api_key_env} is not set or empty",
                }
            )

    backend = cfg.get("secrets.backend", "local")
    if backend == "env":
        results.append(
            {
                "check": "secrets_backend",
                "status": "ok",
                "detail": "env (EnvSecretProvider)",
            }
        )
    elif backend == "keychain":
        try:
            svc = cfg.get("secrets.service_name", "cogito-agent")
            kc = KeychainSecretProvider(service_name=svc)
            if kc.available:
                results.append(
                    {
                        "check": "secrets_backend",
                        "status": "ok",
                        "detail": "keychain (available)",
                    }
                )
            else:
                results.append(
                    {
                        "check": "secrets_backend",
                        "status": "warn",
                        "detail": "keychain (configured but backend unavailable)",
                    }
                )
        except Exception:
            results.append(
                {
                    "check": "secrets_backend",
                    "status": "warn",
                    "detail": "keychain (configured but error loading)",
                }
            )
    else:
        results.append(
            {
                "check": "secrets_backend",
                "status": "ok",
                "detail": "local (LocalSecretsProvider, plaintext SQLite)",
            }
        )

    config_file_exists = os.path.isfile(CONFIG_PATH)
    if config_file_exists:
        results.append(
            {
                "check": "config_file",
                "status": "ok",
                "detail": CONFIG_PATH,
            }
        )
    else:
        results.append(
            {
                "check": "config_file",
                "status": "info",
                "detail": f"{CONFIG_PATH} (not created yet, defaults apply)",
            }
        )

    results.append(
        {
            "check": "db_path",
            "status": "info",
            "detail": os.path.expanduser("~/.cogito/cogito.db"),
        }
    )

    # Embedding health check
    emb_provider = cfg.get("memory.embedding.provider", "mock")
    emb_model = cfg.get("memory.embedding.model", "all-MiniLM-L6-v2")
    if emb_provider in ("disabled", "none"):
        results.append(
            {
                "check": "embedding",
                "status": "info",
                "detail": "disabled (sparse-only retrieval)",
            }
        )
    elif emb_provider == "mock":
        results.append(
            {
                "check": "embedding",
                "status": "ok",
                "detail": f"mock ({emb_model}) - NOT semantic, test only",
            }
        )
    elif emb_provider == "local_sentence_transformer":
        try:
            from cogito_agent.embedding.local import LocalSentenceTransformerEmbeddingProvider

            p = LocalSentenceTransformerEmbeddingProvider(model_name=emb_model)
            h = p.health_check()
            if h.healthy:
                results.append(
                    {
                        "check": "embedding",
                        "status": "ok",
                        "detail": (
                            f"{h.provider_name}/{h.model_name} "
                            f"dim={h.dimension} semantic={h.is_semantic}"
                        ),
                    }
                )
            else:
                results.append(
                    {
                        "check": "embedding",
                        "status": "warn",
                        "detail": f"{h.error_message}",
                    }
                )
        except Exception as e:
            results.append(
                {
                    "check": "embedding",
                    "status": "warn",
                    "detail": f"local provider init failed: {e}",
                }
            )
    elif emb_provider == "openai_compatible":
        base_url = cfg.get("memory.embedding.base_url", "")
        if not base_url:
            results.append(
                {
                    "check": "embedding",
                    "status": "warn",
                    "detail": "openai_compatible provider, but base_url not configured",
                }
            )
        else:
            api_key_secret = cfg.get("memory.embedding.api_key_secret_name", "")
            api_key_env = cfg.get("memory.embedding.api_key_env", "OPENAI_API_KEY")
            has_key = False
            if api_key_secret:
                try:
                    embedding_secret_store: SecretProvider = LocalSecretsProvider()
                    if embedding_secret_store.get_secret(api_key_secret):
                        has_key = True
                except Exception:
                    pass
            if not has_key and api_key_env:
                has_key = bool(os.environ.get(api_key_env))
            if has_key:
                results.append(
                    {
                        "check": "embedding",
                        "status": "ok",
                        "detail": (
                            f"openai_compatible ({emb_model}) base_url={base_url} key=available"
                        ),
                    }
                )
            else:
                results.append(
                    {
                        "check": "embedding",
                        "status": "warn",
                        "detail": (
                            f"openai_compatible ({emb_model}) - API key not found (sparse-only)"
                        ),
                    }
                )
    else:
        results.append(
            {
                "check": "embedding",
                "status": "info",
                "detail": f"provider={emb_provider} (not checked)",
            }
        )

    return results
