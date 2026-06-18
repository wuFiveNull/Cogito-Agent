from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

inbox_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"


def _get_db() -> _Database:
    from cogito_agent.api.app import get_db as _get_shared_db
    return _get_shared_db()


def _ensure_workspace(workspace_id: str) -> None:
    from cogito_agent.storage.repositories import WorkspaceRepository
    db = _get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(workspace_id)
    if ws is None:
        repo.create(workspace_id, workspace_id)


def _redact_item(item: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in item.items():
        if isinstance(v, str):
            result[k] = redact_html(v)
        else:
            result[k] = v
    return result


def _redact_json(raw: str) -> str:
    try:
        parsed = json.loads(raw)
        return redact_html(json.dumps(parsed, indent=2, default=str))
    except (json.JSONDecodeError, TypeError):
        return redact_html(raw)


# ─── Inbox List ─────────────────────────────────────────────────────────────


@inbox_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def inbox_list(
    request: Request,
    status: str = Query("all"),
    q: str = Query(""),
    time_range: str = Query("all"),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()

    params: list[Any] = []
    where_clauses: list[str] = []

    if status and status != "all":
        where_clauses.append("status=?")
        params.append(status)

    if q:
        where_clauses.append("(title LIKE ? OR body LIKE ? OR id LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    if time_range and time_range != "all":
        from datetime import UTC, datetime, timedelta
        days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
        days = days_map.get(time_range, 0)
        if days:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            where_clauses.append("created_at >= ?")
            params.append(cutoff)

    # Get from outbox_messages (with real status tracking) AND inbox_items (legacy)
    # We prioritize outbox_messages as the primary source
    outbox_where = "WHERE workspace_id=?" if CONSOLE_WORKSPACE_ID != "*" else ""
    outbox_params: list[Any] = [CONSOLE_WORKSPACE_ID] if CONSOLE_WORKSPACE_ID != "*" else []

    if status and status != "all":
        outbox_where += " AND status=?" if outbox_where else "WHERE status=?"
        outbox_params.append(status)

    if q:
        like = f"%{q}%"
        outbox_where += " AND (title LIKE ? OR body LIKE ? OR id LIKE ?)"
        outbox_params.extend([like, like, like])

    if time_range and time_range != "all":
        from datetime import UTC, datetime, timedelta
        days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
        days = days_map.get(time_range, 0)
        if days:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            outbox_where += " AND created_at >= ?"
            outbox_params.append(cutoff)

    cur = db.connection.execute(
        "SELECT *, 'outbox' AS source FROM outbox_messages"
        f" {outbox_where} ORDER BY created_at DESC LIMIT 100",
        outbox_params,
    )
    outbox_items = [dict(r) for r in cur.fetchall()]

    # Also get inbox_items for legacy
    if not status or status == "all":
        inbox_cur = db.connection.execute(
            "SELECT *, 'inbox' AS source FROM inbox_items"
            " WHERE workspace_id = ? ORDER BY created_at DESC LIMIT 50",
            (CONSOLE_WORKSPACE_ID,),
        )
        inbox_items = [dict(r) for r in inbox_cur.fetchall()]
    else:
        inbox_items = []

    items = outbox_items + inbox_items
    items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)

    stats = _build_inbox_stats(db)
    stats["total"] = len(items)

    ctx: dict[str, object] = {
        "request": request,
        "title": "Inbox",
        "version": "0.9.0-dev",
        "items": [_redact_item(i) for i in items],
        "stats": stats,
        "status_filter": status,
        "q": q,
        "time_range": time_range,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/inbox.html", ctx)


def _build_inbox_stats(db: _Database) -> dict[str, int]:
    stats: dict[str, int] = {
        "total": 0, "pending": 0, "sent": 0, "failed": 0,
        "retrying": 0, "dead_letter": 0, "skipped": 0,
    }
    try:
        cur = db.connection.execute(
            "SELECT status, COUNT(*) AS cnt FROM outbox_messages"
            " WHERE workspace_id=? GROUP BY status",
            (CONSOLE_WORKSPACE_ID,),
        )
        for r in cur.fetchall():
            stats[str(r["status"])] = r["cnt"]
    except Exception:
        pass
    return stats


# ─── Inbox Detail ────────────────────────────────────────────────────────────


@inbox_router.get("/{item_id}", response_class=HTMLResponse, include_in_schema=False)
async def inbox_detail(request: Request, item_id: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()

    item = None
    source = "outbox"
    cur = db.connection.execute(
        "SELECT * FROM outbox_messages WHERE id = ?", (item_id,)
    )
    row = cur.fetchone()
    if row:
        item = dict(row)
    else:
        cur = db.connection.execute(
            "SELECT * FROM inbox_items WHERE id = ?", (item_id,)
        )
        row = cur.fetchone()
        if row:
            item = dict(row)
            source = "inbox"

    if item is None:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Inbox item '{item_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)

    redacted = _redact_item(item)
    raw_json = ""
    try:
        raw_json = _redact_json(json.dumps(dict(item), indent=2, default=str))
    except Exception:
        pass

    detail_ctx: dict[str, object] = {
        "request": request,
        "title": "Inbox Detail",
        "version": "0.11.0-dev",
        "item": redacted,
        "source": source,
        "raw_json": raw_json,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/inbox_detail.html", detail_ctx)


# ─── Mark Read ────────────────────────────────────────────────────────────────


@inbox_router.post("/{item_id}/read", include_in_schema=False)
async def inbox_mark_read(request: Request, item_id: str) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    db.connection.execute(
        "UPDATE outbox_messages SET read_at = ? WHERE id = ?",
        (now, item_id),
    )
    db.connection.commit()
    referer = request.headers.get("referer", "/console/inbox")
    return RedirectResponse(url=referer, status_code=303)


# ─── Dismiss ──────────────────────────────────────────────────────────────────


@inbox_router.post("/{item_id}/dismiss", include_in_schema=False)
async def inbox_dismiss(request: Request, item_id: str) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    db.connection.execute(
        "UPDATE outbox_messages SET dismissed_at = ?, status = 'skipped' WHERE id = ?",
        (now, item_id),
    )
    db.connection.commit()
    from cogito_agent.governance import AuditLogger
    AuditLogger(db).log(
        actor_id="user",
        action="inbox.dismiss",
        resource=f"outbox:{item_id}",
        workspace_id=CONSOLE_WORKSPACE_ID,
        decision="allow",
        reason="User dismissed notification",
    )
    referer = request.headers.get("referer", "/console/inbox")
    return RedirectResponse(url=referer, status_code=303)


# ─── Retry Failed ─────────────────────────────────────────────────────────────


@inbox_router.post("/{item_id}/retry", include_in_schema=False)
async def inbox_retry(request: Request, item_id: str) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    db.connection.execute(
        "UPDATE outbox_messages SET status = 'pending', last_error = NULL,"
        " next_retry_at = NULL, delivery_attempts = 0 WHERE id = ?",
        (item_id,),
    )
    db.connection.commit()
    from cogito_agent.governance import AuditLogger
    AuditLogger(db).log(
        actor_id="user",
        action="inbox.retry",
        resource=f"outbox:{item_id}",
        workspace_id=CONSOLE_WORKSPACE_ID,
        decision="allow",
        reason="User requested retry",
    )
    referer = request.headers.get("referer", "/console/inbox")
    return RedirectResponse(url=referer, status_code=303)


# ─── Feedback ─────────────────────────────────────────────────────────────────


@inbox_router.post("/{item_id}/feedback", include_in_schema=False)
async def inbox_feedback(
    request: Request,
    item_id: str,
    value: str = Form(...),
) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()

    valid = ["useful", "not_useful", "too_many", "wrong_time", "irrelevant"]
    if value not in valid:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Invalid Feedback",
            "message": f"Invalid feedback value: '{value}'. Valid: {valid}",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=422)

    from cogito_agent.autonomy import FeedbackStore
    from cogito_agent.governance import AuditLogger
    fb = FeedbackStore(db, audit_logger=AuditLogger(db))
    fb.record_feedback(
        decision_id=item_id,
        event_id="",
        value=value,
        workspace_id=CONSOLE_WORKSPACE_ID,
    )
    referer = request.headers.get("referer", "/console/inbox")
    return RedirectResponse(url=referer, status_code=303)
