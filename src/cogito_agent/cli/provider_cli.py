"""cogito provider CLI: list, show, doctor, test."""
from __future__ import annotations

import os
from typing import Any

from cogito_agent.cli.config_manager import get_config
from cogito_agent.models import list_providers
from cogito_agent.models.registry import _PROVIDERS
from cogito_agent.trace.redaction import RedactionHelper

_PROVIDER_ERRORS = {
    "PROVIDER_NOT_CONFIGURED": "Provider '{provider}' is not configured in cogito config",
    "PROVIDER_SECRET_MISSING": "Provider '{provider}' requires a secret (api_key) but none found",
    "PROVIDER_UNREACHABLE": "Provider '{provider}' at '{base_url}' is unreachable",
    "PROVIDER_TIMEOUT": "Provider '{provider}' timed out after {timeout}s",
    "PROVIDER_RATE_LIMITED": "Provider '{provider}' returned rate-limit error",
    "PROVIDER_AUTH_FAILED": "Provider '{provider}' authentication failed",
    "PROVIDER_MODEL_UNAVAILABLE": "Model '{model}' not available for provider '{provider}'",
    "PROVIDER_UNKNOWN_ERROR": "Provider '{provider}' unknown error: {detail}",
}


def _redact(s: str) -> str:
    return RedactionHelper().redact(s)


def _get_provider_info(name: str) -> dict[str, Any]:
    """Return info dict for a provider by name."""
    cfg: Any = _PROVIDERS.get(name, {})
    config_data = get_config()
    secret_ref = config_data.get("model.secret_ref", "")
    has_secret = bool(secret_ref) or bool(os.environ.get("MODEL_API_KEY", ""))
    return {
        "name": name,
        "configured": name == config_data.get("model.provider", ""),
        "requires_secret": name not in ("mock", "ollama"),
        "secret_available": has_secret,
        "base_url": getattr(cfg, "base_url", "") if hasattr(cfg, "base_url") else "",
        "default_model": getattr(cfg, "default_model", "") if hasattr(cfg, "default_model") else "",
    }


def provider_list(args: Any) -> None:
    providers = list_providers()
    if not providers:
        print("  No providers registered.")
        return
    print(f"  Providers ({len(providers)}):")
    for name in sorted(providers):
        info = _get_provider_info(name)
        marker = " *" if info["configured"] else "  "
        secret = " (secret)" if info["requires_secret"] else ""
        st = "configured" if info["configured"] else "available"
        print(f"  {marker} {name}{secret}  [{st}]")


def provider_show(args: Any) -> None:
    name = args.provider_name
    providers = list_providers()
    if name not in providers:
        print(f"  Provider '{name}' not found. Known: {', '.join(sorted(providers))}")
        return
    info = _get_provider_info(name)
    cfg: Any = _PROVIDERS.get(name, {})
    print(f"  Name:              {name}")
    print(f"  Configured:        {'yes' if info['configured'] else 'no'}")
    print(f"  Requires secret:   {'yes' if info['requires_secret'] else 'no'}")
    print(f"  Secret available:  {'yes' if info['secret_available'] else 'no'}")
    if info.get("base_url"):
        print(f"  Default base_url:  {_redact(info['base_url'])}")
    if info.get("default_model"):
        print(f"  Default model:     {info['default_model']}")
    if hasattr(cfg, "supports_streaming"):
        print(f"  Streaming:         {'yes' if cfg.supports_streaming else 'no'}")
    else:
        print("  Streaming:         unknown")


def provider_doctor(args: Any) -> None:
    """Check current provider configuration."""
    from cogito_agent.cli.config_manager import doctor as run_doctor

    checks = run_doctor()
    for c in checks:
        status = c.get("status", "?")
        detail = _redact(c.get("detail", ""))
        tag = {"ok": "OK", "warn": "WARN", "info": "INFO", "error": "ERR"}.get(status, "?")
        print(f"  [{tag}] {c.get('check', '?')}: {detail}")


def provider_test(args: Any) -> None:
    """Test a provider's configuration without making real API calls (default).

    Use --live to execute a real network request.
    """
    from cogito_agent.cli.config_manager import _resolve_api_key, get_config

    name = args.provider_name
    live = getattr(args, "live", False)
    providers = list_providers()

    if name not in providers:
        print(f"  [ERR] Provider '{name}' not found. Known: {', '.join(sorted(providers))}")
        return

    cfg = get_config()
    base_url = cfg.get("model.base_url", "")

    # Check config existence
    if name != cfg.get("model.provider", ""):
        cur = cfg.get("model.provider", "")
        print(f"  [WARN] Provider '{name}' is not current config provider ({cur})")

    # Check secret
    requires_secret = name not in ("mock", "ollama")
    if requires_secret:
        api_key = _resolve_api_key(cfg)
        if not api_key:
            print(f"  [ERR] PROVIDER_SECRET_MISSING: No API key found for '{name}'")
            print("         Set via: cogito config set model.secret_ref <name>")
            print("         Or set:  export MODEL_API_KEY=...")
            return
        print("  [OK]  Secret available (not shown)")

    if name == "mock":
        print("  [OK]  Mock provider (no network needed)")
        return

    # Check base_url
    if not base_url:
        pcfg = _PROVIDERS.get(name)
        if pcfg and hasattr(pcfg, "base_url") and pcfg.base_url:
            base_url = pcfg.base_url
            print(f"  [OK]  Using default base_url: {_redact(base_url)}")
        else:
            base_url = "https://api.openai.com/v1"
            print(f"  [INFO] Using default base_url: {_redact(base_url)}")

    if not live:
        print("  [INFO] Skipping network test (use --live to verify connectivity)")
        return

    # Live test
    try:
        import urllib.error
        import urllib.request

        if name == "ollama":
            test_url = base_url.rstrip("/") + "/api/tags"
        else:
            test_url = base_url.rstrip("/") + "/models"

        req = urllib.request.Request(test_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status < 500:
                print(f"  [OK]  Provider reachable at {_redact(base_url)} (HTTP {resp.status})")
            else:
                print(f"  [WARN] Provider returned HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(f"  [ERR] PROVIDER_AUTH_FAILED: HTTP 401 at {_redact(base_url)}")
        elif e.code == 404:
            print(f"  [INFO] Provider at {_redact(base_url)} returned 404 (may need specific path)")
        else:
            print(f"  [ERR] PROVIDER_UNREACHABLE: HTTP {e.code} at {_redact(base_url)}")
    except urllib.error.URLError as e:
        print(f"  [ERR] PROVIDER_UNREACHABLE: {e.reason} at {_redact(base_url)}")
    except Exception as e:
        print(f"  [ERR] PROVIDER_UNKNOWN_ERROR: {_redact(str(e))}")
