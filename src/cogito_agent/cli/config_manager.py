from __future__ import annotations

import json
import os
from pathlib import Path

from cogito_agent.models import ModelAdapter, get_adapter, list_providers
from cogito_agent.models.registry import _PROVIDERS

CONFIG_DIR = os.path.expanduser("~/.cogito")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG: dict[str, str] = {
    "model.provider": "mock",
    "model.base_url": "",
    "model.model": "",
    "model.api_key_env": "MODEL_API_KEY",
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


def build_model_adapter_from_config() -> ModelAdapter | None:
    cfg = _load_raw()
    provider = cfg.get("model.provider", "mock")
    if provider == "mock":
        return None
    api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    return get_adapter(
        provider=provider,
        model=cfg.get("model.model", ""),
        api_key=api_key,
        base_url=cfg.get("model.base_url", ""),
    )


def doctor() -> list[dict[str, str]]:
    cfg = _load_raw()
    results: list[dict[str, str]] = []

    provider = cfg.get("model.provider", "mock")
    providers = list_providers()
    if provider == "mock":
        results.append({
            "check": "provider", "status": "ok",
            "detail": "mock (no API needed)",
        })
    elif provider in providers:
        results.append({
            "check": "provider", "status": "ok",
            "detail": f"provider '{provider}' registered",
        })
    else:
        known = ", ".join(providers)
        results.append({
            "check": "provider", "status": "warn",
            "detail": f"provider '{provider}' not in known list ({known})",
        })

    base_url = cfg.get("model.base_url", "")
    if provider != "mock" and not base_url:
        pcfg = _PROVIDERS.get(provider)
        if pcfg and pcfg.base_url:
            results.append({
                "check": "base_url", "status": "ok",
                "detail": f"using default: {pcfg.base_url}",
            })
        else:
            results.append({
                "check": "base_url", "status": "warn",
                "detail": "not set, will use OpenAI default",
            })
    elif provider != "mock":
        results.append({
            "check": "base_url", "status": "ok", "detail": base_url,
        })

    model_name = cfg.get("model.model", "")
    if provider != "mock" and not model_name:
        pcfg = _PROVIDERS.get(provider)
        if pcfg and pcfg.default_model:
            results.append({
                "check": "model", "status": "ok",
                "detail": f"using default: {pcfg.default_model}",
            })
        else:
            results.append({
                "check": "model", "status": "warn",
                "detail": "not set, will use env MODEL_NAME or gpt-4o-mini",
            })
    elif provider != "mock":
        results.append({
            "check": "model", "status": "ok", "detail": model_name,
        })

    api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
    if provider != "mock" and api_key_env:
        val = os.environ.get(api_key_env)
        if val:
            results.append({
                "check": "api_key_env", "status": "ok",
                "detail": f"${api_key_env} is set",
            })
        else:
            results.append({
                "check": "api_key_env", "status": "warn",
                "detail": f"${api_key_env} is not set or empty",
            })

    config_file_exists = os.path.isfile(CONFIG_PATH)
    if config_file_exists:
        results.append({
            "check": "config_file", "status": "ok",
            "detail": CONFIG_PATH,
        })
    else:
        results.append({
            "check": "config_file", "status": "info",
            "detail": f"{CONFIG_PATH} (not created yet, defaults apply)",
        })

    results.append({
        "check": "db_path",
        "status": "info",
        "detail": os.path.expanduser("~/.cogito/cogito.db"),
    })

    return results
