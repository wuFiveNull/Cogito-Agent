from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

doctor_router = APIRouter()

CheckList = list[dict[str, object]]


def _get_db():  # type: ignore[no-untyped-def]
    from cogito_agent.api.app import get_db as _get_shared_db
    return _get_shared_db()


def _cfg() -> dict[str, str]:
    try:
        from cogito_agent.cli.config_manager import get_config
        return get_config()
    except Exception:
        return {}


def _count(table: str, where: str = "") -> int:
    try:
        from cogito_agent.storage import Database
        db = Database()
        db.initialize()
        sql = f"SELECT COUNT(*) AS cnt FROM {table}"
        if where:
            sql += f" WHERE {where}"
        row = db.connection.execute(sql).fetchone()
        db.close()
        return row["cnt"] if row else 0
    except Exception:
        return -1


def _build_checks() -> CheckList:
    checks: CheckList = []

    checks.extend(_core_checks())
    checks.extend(_db_checks())
    checks.extend(_provider_checks())
    checks.extend(_secrets_checks())
    checks.extend(_governance_checks())
    checks.extend(_autonomy_checks())
    checks.extend(_console_checks())

    return checks


def _check(
    section: str, name: str, status: str,
    message: str, details: object = None,
) -> dict[str, object]:
    c: dict[str, object] = {
        "section": section,
        "name": name,
        "status": status,
        "message": redact_html(message),
    }
    if details is not None:
        c["details"] = details
    return c


def _core_checks() -> CheckList:
    checks: CheckList = []
    try:
        version = os.environ.get("COGITO_CONSOLE_VERSION", "0.9.0-dev")
        checks.append(_check("core", "app_version", "ok", f"v{version}"))
        checks.append(_check("core", "python_version", "ok", sys.version.split()[0]))
        checks.append(_check("core", "platform", "ok", sys.platform))
    except Exception as exc:
        checks.append(_check("core", "core_info", "error", str(exc)))

    try:
        cwd = os.getcwd()
        checks.append(_check("core", "cwd", "ok", redact_html(cwd)))
    except Exception:
        checks.append(_check("core", "cwd", "error", "Cannot determine CWD"))

    try:
        from cogito_agent.cli.config_manager import get_config
        cfg = get_config()
        config_ok = len(cfg) > 0
        checks.append(_check(
            "core", "config_load", "ok" if config_ok else "warning",
            "Config loaded" if config_ok else "Config empty or unreadable",
        ))
    except Exception as exc:
        checks.append(_check("core", "config_load", "error", redact_html(str(exc))))

    pkg_checks = [
        ("fastapi", "fastapi"), ("pydantic", "pydantic"),
        ("jinja2", "jinja2"), ("sqlite3", "sqlite3"),
    ]
    pkg_ok = 0
    pkg_err = 0
    for name, mod in pkg_checks:
        try:
            __import__(mod)
            pkg_ok += 1
        except ImportError:
            pkg_err += 1
    checks.append(_check(
        "core", "packages", "ok" if pkg_err == 0 else "warning",
        f"{pkg_ok}/{len(pkg_checks)} core packages available",
    ))

    return checks


def _db_checks() -> CheckList:
    checks: CheckList = []
    try:
        from cogito_agent.storage import Database
        db = Database()
        db.initialize()
        db.migrate()
        ver = db.current_version()
        path = os.environ.get("COGITO_DB_PATH", "~/.cogito/cogito.db")
        checks.append(_check("database", "db_reachable", "ok", "Database reachable"))
        checks.append(_check("database", "db_path", "ok", redact_html(path)))
        checks.append(_check("database", "schema_version", "ok", f"v{ver}"))
        db.close()
    except Exception as exc:
        checks.append(_check("database", "db_reachable", "error", redact_html(str(exc))))
        return checks

    tables = [
        ("memories", ""),
        ("memory_candidates", ""),
        ("approval_records", ""),
        ("traces", ""),
        ("audit_logs", ""),
        ("notification_decisions", ""),
        ("outbox_messages", ""),
        ("feedback_entries", ""),
    ]
    for table, where in tables:
        try:
            cnt = _count(table, where)
            checks.append(_check(
                "database", f"table_{table}", "ok",
                f"{table}: {cnt} rows",
            ))
        except Exception as exc:
            checks.append(_check(
                "database", f"table_{table}", "warning",
                f"{table}: count error - {redact_html(str(exc))}",
            ))

    return checks


def _provider_checks() -> CheckList:
    checks: CheckList = []
    cfg = _cfg()
    provider = cfg.get("model.provider", "mock")

    try:
        from cogito_agent.models.registry import _PROVIDERS
        providers = list(_PROVIDERS.keys())
    except Exception:
        providers = []

    if provider == "mock":
        checks.append(_check("provider", "provider", "ok", "mock (no API needed)"))
    elif provider in providers:
        checks.append(_check("provider", "provider", "ok", f"'{provider}' registered"))
    else:
        known = ", ".join(providers) if providers else "none registered"
        checks.append(_check("provider", "provider", "warning", f"'{provider}' not in known list ({known})"))  # noqa: E501

    model_name = cfg.get("model.model", "")
    if provider == "mock":
        pass
    elif model_name:
        checks.append(_check("provider", "model", "ok", model_name))
    else:
        checks.append(_check("provider", "model", "warning", "not configured (will use default)"))

    streaming = cfg.get("model.streaming_enabled", "true")
    checks.append(_check("provider", "streaming", "ok", f"streaming_enabled={streaming}"))

    timeout = cfg.get("model.timeout_seconds", "60")
    checks.append(_check("provider", "timeout", "ok", f"{timeout}s"))

    max_retries = cfg.get("model.max_retries", "2")
    checks.append(_check("provider", "max_retries", "ok", max_retries))

    base_url = cfg.get("model.base_url", "")
    if provider != "mock" and not base_url:
        pcfg = _PROVIDERS.get(provider) if providers else None
        if pcfg and hasattr(pcfg, "base_url") and pcfg.base_url:
            checks.append(_check("provider", "base_url", "ok", f"using default: {pcfg.base_url}"))
        else:
            checks.append(_check("provider", "base_url", "warning", "not set"))
    elif provider != "mock":
        checks.append(_check("provider", "base_url", "ok", redact_html(base_url)))

    secret_ref = cfg.get("model.secret_ref", "")
    if provider != "mock" and secret_ref:
        try:
            from cogito_agent.security import get_provider_from_config
            sp = get_provider_from_config(cfg)
            sv = sp.get_secret(secret_ref)
            if sv is not None:
                checks.append(_check("provider", "secret_ref", "ok", "resolved"))
            else:
                checks.append(_check("provider", "secret_ref", "warning",
                    "configured but not found"))
        except Exception:
            checks.append(_check("provider", "secret_ref", "warning", "error resolving"))
    elif provider != "mock":
        api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
        val = os.environ.get(api_key_env)
        if val:
            checks.append(_check("provider", "api_key_env", "ok",
                f"${api_key_env} is set (legacy)"))
        else:
            checks.append(_check("provider", "api_key_env", "warning", f"${api_key_env} not set"))

    checks.append(_check("provider", "live_check", "skipped", "not run (use ?live=1 to enable)"))

    return checks


def _secrets_checks() -> CheckList:
    checks: CheckList = []
    cfg = _cfg()
    backend = cfg.get("secrets.backend", "local")

    checks.append(_check("secrets", "backend", "ok", backend))

    try:
        from cogito_agent.security import get_provider_from_config
        provider = get_provider_from_config(cfg)
        keys = provider.list_keys()
        available = len(keys) > 0 or backend == "local"
        checks.append(_check(
            "secrets", "available", "ok" if available else "warning",
            f"available ({len(keys)} keys)" if available else "no secrets found",
        ))
    except Exception as exc:
        checks.append(_check("secrets", "available", "warning", redact_html(str(exc))))

    service_name = cfg.get("secrets.service_name", "cogito-agent")
    checks.append(_check("secrets", "service_name", "ok", service_name))

    if backend == "local":
        local_path = cfg.get("secrets.local_path", "")
        if not local_path:
            local_path = str(Path.home() / ".cogito" / "secrets.db")
        checks.append(_check("secrets", "local_path", "ok", redact_html(local_path)))
    elif backend == "keychain":
        try:
            from cogito_agent.security import KeychainSecretProvider
            kc = KeychainSecretProvider(service_name=service_name)
            if kc.available:
                checks.append(_check("secrets", "keychain", "ok", "available"))
            else:
                checks.append(_check("secrets", "keychain", "warning", "unavailable"))
        except Exception as exc:
            checks.append(_check("secrets", "keychain", "warning", redact_html(str(exc))))
    elif backend == "env":
        checks.append(_check("secrets", "env_provider", "ok", "EnvSecretProvider"))

    try:
        env_secrets_count = len([k for k in os.environ if k.startswith("COGITO_")])
        checks.append(_check(
            "secrets", "env_presence", "ok",
            f"{env_secrets_count} COGITO_* env vars present (values not shown)",
        ))
    except Exception:
        checks.append(_check("secrets", "env_presence", "warning", "cannot enumerate"))

    return checks


def _governance_checks() -> CheckList:
    checks: CheckList = []

    try:
        from cogito_agent.governance import PolicyEngine
        PolicyEngine()
        checks.append(_check("governance", "policy_engine", "ok", "available"))
    except Exception:
        checks.append(_check("governance", "policy_engine", "warning", "not available"))

    try:
        from cogito_agent.storage import Database
        from cogito_agent.storage.repositories import ApprovalRepository
        db = Database()
        db.initialize()
        ApprovalRepository(db)
        checks.append(_check("governance", "approval_repo", "ok", "available"))
        db.close()
    except Exception:
        checks.append(_check("governance", "approval_repo", "warning", "not available"))

    try:
        from cogito_agent.governance import AuditLogger
        from cogito_agent.storage import Database
        db = Database()
        db.initialize()
        AuditLogger(db)
        checks.append(_check("governance", "audit_store", "ok", "available"))
        db.close()
    except Exception:
        checks.append(_check("governance", "audit_store", "warning", "not available"))

    try:
        from cogito_agent.storage import Database
        from cogito_agent.trace import Tracer
        db = Database()
        db.initialize()
        Tracer(db)
        checks.append(_check("governance", "trace_store", "ok", "available"))
        db.close()
    except Exception:
        checks.append(_check("governance", "trace_store", "warning", "not available"))

    try:
        from datetime import UTC, datetime, timedelta
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        from cogito_agent.storage import Database
        db = Database()
        db.initialize()
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM audit_logs WHERE created_at >= ?", (cutoff,))
        row = cur.fetchone()
        audit_count = row["cnt"] if row else 0
        db.close()
        checks.append(_check("governance", "recent_audit", "ok", f"{audit_count} events in 24h"))
    except Exception:
        checks.append(_check("governance", "recent_audit", "warning", "count unavailable"))

    try:
        cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        from cogito_agent.storage import Database
        db = Database()
        db.initialize()
        cur = db.connection.execute(
            "SELECT COUNT(*) AS cnt FROM traces WHERE started_at >= ?", (cutoff,))
        row = cur.fetchone()
        trace_count = row["cnt"] if row else 0
        db.close()
        checks.append(_check("governance", "recent_traces", "ok", f"{trace_count} traces in 24h"))
    except Exception:
        checks.append(_check("governance", "recent_traces", "warning", "count unavailable"))

    return checks


def _autonomy_checks() -> CheckList:
    checks: CheckList = []
    cfg = _cfg()

    enabled = cfg.get("autonomy.enabled", "true")
    status = "ok" if enabled == "true" else "warning"
    checks.append(_check("autonomy", "enabled", status, f"autonomy.enabled={enabled}"))

    checks.append(_check("autonomy", "quiet_hours", "ok",
        f"start={cfg.get('autonomy.quiet_hours.start', '22:00')} "
        f"end={cfg.get('autonomy.quiet_hours.end', '08:00')} "
        f"enabled={cfg.get('autonomy.quiet_hours.enabled', 'true')}"))

    checks.append(_check("autonomy", "quota", "ok",
        f"daily={cfg.get('autonomy.notification.daily_quota', '5')} "
        f"hourly={cfg.get('autonomy.notification.hourly_quota', '2')}"))

    checks.append(_check("autonomy", "dedup", "ok",
        f"window={cfg.get('autonomy.dedup.window_minutes', '120')}min"))

    try:
        from cogito_agent.autonomy import DecisionStore, FeedbackStore, Outbox
        from cogito_agent.storage import Database
        db = Database()
        db.initialize()
        DecisionStore(db)
        checks.append(_check("autonomy", "decision_store", "ok", "available"))
        Outbox(db)
        checks.append(_check("autonomy", "outbox_store", "ok", "available"))
        from cogito_agent.governance import AuditLogger
        FeedbackStore(db, audit_logger=AuditLogger(db))
        checks.append(_check("autonomy", "feedback_store", "ok", "available"))
        db.close()
    except Exception as exc:
        checks.append(_check("autonomy", "stores", "warning", redact_html(str(exc))))

    return checks


def _console_checks() -> CheckList:
    checks: CheckList = []

    here = Path(__file__).resolve().parent
    tmpl_dir = here / "templates"
    static_dir = here / "static"

    if tmpl_dir.is_dir():
        tmpl_count = len(list(tmpl_dir.glob("**/*.html")))
        checks.append(_check("console", "templates", "ok", f"available ({tmpl_count} files)"))
    else:
        checks.append(_check("console", "templates", "error", "not found"))

    if static_dir.is_dir():
        css_files = list(static_dir.glob("*.css"))
        js_files = list(static_dir.glob("*.js"))
        checks.append(_check("console", "static_assets", "ok",
            f"available ({len(css_files)} CSS, {len(js_files)} JS)"))
    else:
        checks.append(_check("console", "static_assets", "error", "not found"))

    htmx_path = static_dir / "htmx.min.js"
    if htmx_path.is_file():
        size = htmx_path.stat().st_size
        checks.append(_check("console", "htmx", "ok", f"available ({size} bytes)"))
    else:
        checks.append(_check("console", "htmx", "warning", "not found"))

    import os
    api_key = os.environ.get("COGITO_API_KEY", "")
    if api_key:
        checks.append(_check("console", "auth_middleware", "ok", "active (COGITO_API_KEY set)"))
    else:
        checks.append(_check("console", "auth_middleware", "ok",
            "inactive (no API key configured)"))

    checks.append(_check("console", "limitations", "info",
        "No real Telegram/Feishu delivery; Config/Doctor read-only in v0.8"))

    return checks


def _overall_status(checks: CheckList) -> str:
    has_error = any(c.get("status") == "error" for c in checks)
    has_warning = any(c.get("status") == "warning" for c in checks)
    if has_error:
        return "error"
    if has_warning:
        return "warning"
    return "ok"


# ─── Doctor Page ──────────────────────────────────────────────────────────────


@doctor_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def doctor_page(request: Request) -> HTMLResponse:
    checks = _build_checks()
    overall = _overall_status(checks)

    sections_map: dict[str, list[dict[str, object]]] = {}
    for c in checks:
        sec = str(c.get("section", "other"))
        sections_map.setdefault(sec, []).append(c)

    ctx: dict[str, object] = {
        "request": request,
        "title": "Doctor",
        "version": "0.9.0-dev",
        "overall": overall,
        "sections": sections_map,
        "checks_raw": checks,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/doctor.html", ctx)


# ─── Doctor JSON API ──────────────────────────────────────────────────────────


@doctor_router.get("/api", include_in_schema=False)
async def doctor_api(request: Request, live: str = Query("")) -> JSONResponse:
    if live and live not in ("", "0", "false"):
        return JSONResponse(
            status_code=501,
            content={
                "status": "error",
                "version": os.environ.get("COGITO_CONSOLE_VERSION", "0.9.0-dev"),
                "checks": [{
                    "section": "provider",
                    "name": "live_check",
                    "status": "skipped",
                    "message": "Live provider check not implemented in console viewer",
                }],
                "limitations": ["Live provider check not available in console viewer"],
            },
        )

    checks = _build_checks()
    overall = _overall_status(checks)
    return JSONResponse({
        "status": overall,
        "version": os.environ.get("COGITO_CONSOLE_VERSION", "0.9.0-dev"),
        "checks": checks,
        "limitations": [
            "No real Telegram/Feishu delivery for outbox",
            "Live provider check not run by default",
            "Config viewer is read-only in v0.8 Phase 7",
        ],
    })
