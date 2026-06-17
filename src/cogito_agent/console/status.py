from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from starlette.responses import JSONResponse

from cogito_agent.storage import Database

status_router = APIRouter()

try:
    from cogito_agent.cli.config_manager import get_config

    _CONFIG_LOADER = get_config
except Exception:
    def _empty_config() -> dict[str, str]:
        return {}
    _CONFIG_LOADER = _empty_config


def _count(table: str, column: str = "id", where: str = "") -> int:
    try:
        db = Database()
        db.initialize()
        sql = f"SELECT COUNT({column}) AS cnt FROM {table}"
        if where:
            sql += f" WHERE {where}"
        cur = db.connection.execute(sql)
        row = cur.fetchone()
        db.close()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def _count_since(table: str, column: str = "id", hours: int = 24) -> int:
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    return _count(table, where=f"created_at >= '{cutoff}'")


def _db_info() -> dict[str, object]:
    try:
        db = Database()
        db.initialize()
        ver = db.current_version()
        path = os.environ.get("COGITO_DB_PATH", ":memory:")
        db.close()
        return {"ok": True, "path": path, "migration_version": ver}
    except Exception as exc:
        return {"ok": False, "path": "", "error": str(exc)}


def _model_info() -> dict[str, object]:
    cfg = _CONFIG_LOADER()
    return {
        "provider": cfg.get("model.provider", "mock"),
        "streaming_enabled": cfg.get("model.streaming_enabled", "true").lower() == "true",
        "timeout_seconds": int(cfg.get("model.timeout_seconds", "60")),
    }


def _secrets_info() -> dict[str, object]:
    cfg = _CONFIG_LOADER()
    backend = cfg.get("secrets.backend", "local")
    available = False
    try:
        from cogito_agent.security import get_provider_from_config

        provider = get_provider_from_config(cfg)
        keys = provider.list_keys()
        available = len(keys) > 0
    except Exception:
        pass
    return {"backend": backend, "available": available}


def build_status() -> dict[str, object]:
    db = _db_info()
    model = _model_info()
    secrets = _secrets_info()

    return {
        "version": os.environ.get("COGITO_CONSOLE_VERSION", "0.8.0-dev"),
        "db": db,
        "model": model,
        "secrets": secrets,
        "counts": {
            "memories": _count("memories"),
            "memory_candidates_pending": _count(
                "memory_candidates", where="status = 'pending'"
            ),
            "approvals_pending": _count(
                "approval_records", where="status = 'pending'"
            ),
            "autonomy_outbox_pending": _count(
                "outbox_messages", where="status = 'pending'"
            ),
            "autonomy_decisions_24h": _count_since("notification_decisions"),
            "audit_events_24h": _count_since("audit_logs"),
            "traces_24h": _count_since("traces"),
        },
        "limitations": [
            "No real Telegram/Feishu delivery for outbox",
            "Config viewer is read-only (no editing)",
            "Live provider check not available in console doctor",
        ],
    }


@status_router.get("")
async def status_api() -> JSONResponse:
    return JSONResponse(build_status())
