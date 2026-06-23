from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

audit_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"


# ─── helpers ─────────────────────────────────────────────────────────────────


def _get_db() -> _Database:
    from cogito_agent.storage import get_db

    return get_db()


def _ensure_workspace(workspace_id: str) -> None:
    from cogito_agent.application import WorkspaceApplicationService

    WorkspaceApplicationService(_get_db()).ensure_workspace(workspace_id)


def _list_audit(
    workspace_id: str,
    actor: str = "",
    operation: str = "",
    q: str = "",
    time_range: str = "",
    limit: int = 100,
) -> list[dict[str, object]]:
    db = _get_db()
    params: list[Any] = []
    where_clauses: list[str] = []

    if workspace_id and workspace_id != "*":
        where_clauses.append("al.workspace_id=?")
        params.append(workspace_id)

    if actor:
        where_clauses.append("al.actor_id=?")
        params.append(actor)

    if operation:
        where_clauses.append("al.action LIKE ?")
        params.append(f"%{operation}%")

    if q:
        where_clauses.append(
            "(al.actor_id LIKE ? OR al.action LIKE ?"
            " OR al.resource LIKE ? OR al.trace_id LIKE ?"
            " OR al.reason LIKE ?)"
        )
        like = f"%{q}%"
        for _ in range(5):
            params.append(like)

    cutoff = ""
    if time_range:
        days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
        days = days_map.get(time_range, 0)
        if days:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    where = ""
    if where_clauses:
        where = "WHERE " + " AND ".join(where_clauses)

    from cogito_agent.storage.repositories import AuditRepository
    rows = AuditRepository(db).list_by_advanced_filters(
        workspace_id=workspace_id,
        actor=actor or "",
        operation=operation or "",
        q=q or "",
        since=cutoff if time_range else "",
        limit=limit,
    )
    return [dict(r) for r in rows]


def _audit_stats(workspace_id: str) -> dict[str, int]:
    db = _get_db()
    from cogito_agent.storage.repositories import AuditRepository
    total = AuditRepository(db).count_by_filters(workspace_id=workspace_id)
    return {"total": total}


def _redact_item(item: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in item.items():
        if isinstance(v, str):
            result[k] = redact_html(v)
        else:
            result[k] = v
    return result


# ─── List page ────────────────────────────────────────────────────────────────


@audit_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def audit_page(
    request: Request,
    actor: str = Query(""),
    operation: str = Query(""),
    q: str = Query(""),
    time_range: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    stats = _audit_stats(CONSOLE_WORKSPACE_ID)
    items = _list_audit(CONSOLE_WORKSPACE_ID, actor, operation, q, time_range)
    items = [_redact_item(i) for i in items]

    ctx: dict[str, object] = {
        "request": request,
        "title": "Audit",
        "version": APP_VERSION,
        "stats": stats,
        "actor": actor,
        "operation": operation,
        "q": q,
        "time_range": time_range,
        "items": items,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/audit.html", ctx)


# ─── Detail page ──────────────────────────────────────────────────────────────


@audit_router.get("/{audit_id}", response_class=HTMLResponse, include_in_schema=False)
async def audit_detail(request: Request, audit_id: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.storage.repositories import AuditRepository
    row = AuditRepository(db).get_by_id(audit_id)
    if row is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Audit event '{audit_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", error_ctx, status_code=404)

    item = _redact_item(dict(row))

    details_raw = item.get("details", "{}")
    if isinstance(details_raw, str):
        try:
            parsed = json.loads(details_raw)
            if isinstance(parsed, dict):
                details_redacted = redact_html(json.dumps(parsed, indent=2))
            else:
                details_redacted = redact_html(details_raw)
        except (json.JSONDecodeError, TypeError):
            details_redacted = redact_html(str(details_raw))
    else:
        details_redacted = redact_html(str(details_raw))

    detail_ctx: dict[str, object] = {
        "request": request,
        "title": "Audit Detail",
        "version": APP_VERSION,
        "item": item,
        "details_redacted": details_redacted,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/audit_detail.html", detail_ctx)
