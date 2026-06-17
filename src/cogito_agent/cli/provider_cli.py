"""cogito provider CLI: list, show, doctor, test."""
from __future__ import annotations

from typing import Any

from cogito_agent.cli.config_manager import _resolve_api_key, get_config
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


def _check_secret_available() -> bool:
    """Real check: try to resolve API key from secret_ref or api_key_env."""
    cfg = get_config()
    key = _resolve_api_key(cfg)
    return bool(key)


def _get_provider_info(name: str) -> dict[str, Any]:
    """Return info dict for a provider by name."""
    cfg: Any = _PROVIDERS.get(name, {})
    config_data = get_config()
    return {
        "name": name,
        "configured": name == config_data.get("model.provider", ""),
        "requires_secret": name not in ("mock", "ollama"),
        "secret_available": _check_secret_available() if name not in ("mock",) else True,
        "secret_ref": config_data.get("model.secret_ref", ""),
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

    cfg = get_config()
    provider = cfg.get("model.provider", "mock")

    # Check provider listing
    providers = list_providers()
    if provider == "mock":
        print("  [OK]  provider: mock (no API needed)")
    elif provider in providers:
        print(f"  [OK]  provider: '{provider}' registered")
    else:
        print(f"  [WARN] provider: '{provider}' not in known list ({', '.join(sorted(providers))})")

    # Check secret availability
    if provider not in ("mock",):
        if _check_secret_available():
            sr = cfg.get("model.secret_ref", "")
            if sr:
                print(f"  [OK]  secret_ref: '{sr}' available")
            else:
                print("  [OK]  api_key_env: set (legacy)")
        else:
            sr = cfg.get("model.secret_ref", "")
            if sr:
                print(f"  [WARN] secret_ref: '{sr}' configured but NOT available")
                print(f"         Set: echo -n '<value>' | cogito secrets set {sr}")
            else:
                print("  [WARN] api_key_env: not set")
                print("         Set: cogito config set model.secret_ref <name>")
                print("         Or:  export MODEL_API_KEY=...")

    # Check streaming config
    se = cfg.get("model.streaming_enabled", "true")
    if se.lower() == "true":
        print("  [OK]  streaming_enabled: true")
    else:
        print("  [INFO] streaming_enabled: false (adapter may still support streaming)")

    # Check timeout
    try:
        to = int(cfg.get("model.timeout_seconds", "60"))
        print(f"  [OK]  timeout: {to}s" if to > 0 else f"  [WARN] timeout: {to}s (invalid)")
    except ValueError:
        print("  [WARN] timeout_seconds: not a valid integer")

    # Check max_retries
    try:
        mr = int(cfg.get("model.max_retries", "2"))
        print(f"  [OK]  max_retries: {mr}" if mr >= 0 else "  [WARN] max_retries: negative")
    except ValueError:
        print("  [WARN] max_retries: not a valid integer")

    # Delegate to base doctor for remaining checks
    checks = run_doctor()
    for c in checks:
        status = c.get("status", "?")
        detail = _redact(c.get("detail", ""))
        tag = {"ok": "OK", "warn": "WARN", "info": "INFO", "error": "ERR"}.get(status, "?")
        print(f"  [{tag}] {c.get('check', '?')}: {detail}")


def _health_strategy(name: str, base_url: str) -> tuple[str, str | None]:
    """Return (health_url, error_if_missing_secret) for a provider."""
    strategies = {
        "ollama": (base_url.rstrip("/") + "/api/tags", None),
        "openai": (base_url.rstrip("/") + "/models", None),
    }
    # Generic openai-compatible
    return strategies.get(name, (base_url.rstrip("/") + "/models", None))


def provider_test(args: Any) -> None:
    """Test a provider's configuration without making real API calls (default).

    Use --live to execute a real network request.
    """
    from cogito_agent.cli.config_manager import _resolve_api_key, get_config

    name = args.provider_name
    live = getattr(args, "live", False)
    providers = list_providers()

    if name not in providers:
        print(f"  [ERR] PROVIDER_NOT_CONFIGURED: Provider '{name}' not found")
        print(f"         Known: {', '.join(sorted(providers))}")
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
            sr = cfg.get("model.secret_ref", "")
            if sr:
                print(f"         Secret ref '{sr}' configured but not resolvable")
                print(f"         Set: echo -n '<value>' | cogito secrets set {sr}")
            else:
                print("         Set via: cogito config set model.secret_ref <name>")
                print("         Or:  export MODEL_API_KEY=...")
            return
        print("  [OK]  Secret available (not shown)")

    if name == "mock":
        print("  [OK]  Mock provider (no network needed)")
        return

    # Resolve base_url
    if not base_url:
        pcfg = _PROVIDERS.get(name)
        if pcfg and hasattr(pcfg, "base_url") and pcfg.base_url:
            base_url = pcfg.base_url
            print("  [OK]  Using default base_url")
        else:
            base_url = "https://api.openai.com/v1"
            print("  [INFO] Using default base_url (https://api.openai.com/v1)")

    if not live:
        print("  [INFO] Skipping network test (use --live to verify connectivity)")
        return

    # Live test
    health_url, _ = _health_strategy(name, base_url)
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(health_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status < 500:
                print(f"  [OK]  PROVIDER_REACHABLE: HTTP {resp.status}")
            else:
                print(f"  [WARN] PROVIDER_UNREACHABLE: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("  [ERR] PROVIDER_AUTH_FAILED: HTTP 401")
        elif e.code == 404:
            print("  [INFO] Provider returned 404 (endpoint may differ)")
        else:
            print(f"  [ERR] PROVIDER_UNREACHABLE: HTTP {e.code}")
    except urllib.error.URLError:
        print("  [ERR] PROVIDER_UNREACHABLE: connection failed")
    except Exception:
        print("  [ERR] PROVIDER_UNKNOWN_ERROR")
