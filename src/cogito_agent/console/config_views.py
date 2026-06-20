from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

config_router = APIRouter()


def _get_config() -> dict[str, str]:
    try:
        from cogito_agent.cli.config_manager import get_config
        return get_config()
    except Exception as exc:
        logger.warning("config load failed: %s", exc)
        return {}


def _build_sections(cfg: dict[str, str]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []

    env = _env_summary()
    sections.append({
        "title": "Environment",
        "rows": [
            {"key": "App Version", "value": env.get("version", "unknown")},
            {"key": "Python Version", "value": env.get("python_version", "unknown")},
            {"key": "Platform", "value": env.get("platform", "unknown")},
            {"key": "Config File", "value": env.get("config_path", "unknown")},
            {"key": "DB Path", "value": redact_html(env.get("db_path", "unknown"))},
        ],
    })

    sections.append({
        "title": "Model Provider",
        "rows": [
            {"key": "Provider", "value": cfg.get("model.provider", "mock")},
            {"key": "Model Name", "value": cfg.get("model.model", "") or "(default)"},
            {"key": "Base URL", "value": redact_html(cfg.get("model.base_url", "") or "(default)")},
            {"key": "Streaming Enabled", "value": cfg.get("model.streaming_enabled", "true")},
            {"key": "Timeout (s)", "value": cfg.get("model.timeout_seconds", "60")},
            {"key": "Max Retries", "value": cfg.get("model.max_retries", "2")},
            {"key": "API Key Source", "value": _secret_ref_summary(cfg)},
        ],
    })

    sections.append({
        "title": "Secrets",
        "rows": [
            {"key": "Backend", "value": cfg.get("secrets.backend", "local")},
            {"key": "Service Name", "value": cfg.get("secrets.service_name", "cogito-agent")},
            {"key": "Local Path",
             "value": redact_html(cfg.get("secrets.local_path", "") or "(default)")},
        ],
    })

    rows: list[dict[str, str]] = [
        {"key": "Enabled", "value": cfg.get("autonomy.enabled", "true")},
    ]
    rows.append(
        {"key": "Quiet Hours Enabled", "value": cfg.get("autonomy.quiet_hours.enabled", "true")}
    )
    rows.append(
        {"key": "Quiet Hours Start", "value": cfg.get("autonomy.quiet_hours.start", "22:00")}
    )
    rows.append(
        {"key": "Quiet Hours End", "value": cfg.get("autonomy.quiet_hours.end", "08:00")}
    )
    rows.append(
        {"key": "Quiet Hours Timezone", "value": cfg.get("autonomy.quiet_hours.timezone", "local")}
    )
    rows.append(
        {"key": "Daily Quota", "value": cfg.get("autonomy.notification.daily_quota", "5")}
    )
    rows.append(
        {"key": "Hourly Quota", "value": cfg.get("autonomy.notification.hourly_quota", "2")}
    )
    rows.append(
        {"key": "Urgent Bypass Quiet Hours",
         "value": cfg.get("autonomy.notification.urgent_bypass_quiet_hours", "true")}
    )
    rows.append(
        {"key": "Urgent Bypass Quota",
         "value": cfg.get("autonomy.notification.urgent_bypass_quota", "true")}
    )
    rows.append(
        {"key": "Dedup Window (min)", "value": cfg.get("autonomy.dedup.window_minutes", "120")}
    )
    rows.append(
        {"key": "Feedback Enabled", "value": cfg.get("autonomy.feedback.enabled", "true")}
    )
    sections.append({
        "title": "Autonomy",
        "rows": rows,
    })

    auth_enabled = _auth_enabled_summary()
    sections.append({
        "title": "Auth & Console",
        "rows": [
            {"key": "Auth Enabled", "value": auth_enabled},
            {"key": "API Key Set", "value": "yes (redacted)" if _is_api_key_set() else "no"},
            {"key": "Console Status", "value": "enabled"},
        ],
    })

    return sections


def _env_summary() -> dict[str, str]:
    import os
    import sys

    from cogito_agent.cli.config_manager import CONFIG_PATH
    from cogito_agent.storage import Database
    result: dict[str, str] = {
        "version": os.environ.get("COGITO_CONSOLE_VERSION", APP_VERSION),
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "config_path": CONFIG_PATH,
    }
    try:
        db = Database()
        db.initialize()
        result["db_path"] = os.environ.get("COGITO_DB_PATH", "~/.cogito/cogito.db")
        db.close()
    except Exception:
        result["db_path"] = "unknown"
    return result


def _secret_ref_summary(cfg: dict[str, str]) -> str:
    secret_ref = cfg.get("model.secret_ref", "")
    if secret_ref:
        return "secret_ref configured (resolved status: see Doctor)"
    api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
    import os
    if os.environ.get(api_key_env):
        return f"env var ${api_key_env} set (legacy)"
    return "not configured (will use mock or env fallback)"


def _auth_enabled_summary() -> str:
    import os
    key = os.environ.get("COGITO_API_KEY", "")
    return "enabled" if key else "disabled (no COGITO_API_KEY set)"


def _is_api_key_set() -> bool:
    import os
    return bool(os.environ.get("COGITO_API_KEY", ""))


@config_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def config_page(request: Request) -> HTMLResponse:
    cfg = _get_config()
    sections = _build_sections(cfg)
    ctx: dict[str, object] = {
        "request": request,
        "title": "Configuration",
        "version": APP_VERSION,
        "sections": sections,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/config.html", ctx)
