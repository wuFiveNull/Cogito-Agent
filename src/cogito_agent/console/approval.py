from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

approval_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"
CONSOLE_ACTOR = "console"


# ─── helpers ─────────────────────────────────────────────────────────────────


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


def _list_approvals(
    workspace_id: str,
    status: str = "",
    risk: str = "",
    q: str = "",
    limit: int = 100,
) -> list[dict[str, object]]:
    db = _get_db()
    sql = "SELECT * FROM approval_records WHERE workspace_id=?"
    params: list[Any] = [workspace_id]

    if status and status != "all":
        sql += " AND status=?"
        params.append(status)

    if q:
        sql += " AND (capability_name LIKE ? OR operation LIKE ? OR resource LIKE ?)"
        like = f"%{q}%"
        params.append(like)
        params.append(like)
        params.append(like)

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.connection.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _approval_stats(workspace_id: str) -> dict[str, int]:
    db = _get_db()
    cur = db.connection
    total = cur.execute(
        "SELECT COUNT(*) FROM approval_records WHERE workspace_id=?", (workspace_id,)
    ).fetchone()[0]
    pending = cur.execute(
        "SELECT COUNT(*) FROM approval_records WHERE workspace_id=? AND status='pending'",
        (workspace_id,),
    ).fetchone()[0]
    approved = cur.execute(
        "SELECT COUNT(*) FROM approval_records WHERE workspace_id=? AND status='approved'",
        (workspace_id,),
    ).fetchone()[0]
    rejected = cur.execute(
        "SELECT COUNT(*) FROM approval_records WHERE workspace_id=? AND status='rejected'",
        (workspace_id,),
    ).fetchone()[0]
    return {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
    }


def _redact_item(item: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in item.items():
        if isinstance(v, str):
            result[k] = redact_html(v)
        else:
            result[k] = v
    return result


def _audit_log(
    actor: str,
    action: str,
    resource: str,
    workspace_id: str,
    details: dict[str, object] | None = None,
    request_id: str = "",
) -> None:
    from cogito_agent.governance.audit import AuditLogger

    db = _get_db()
    AuditLogger(db).log(
        actor_id=actor,
        action=action,
        resource=resource,
        workspace_id=workspace_id,
        details=json.dumps(details or {}, default=str),
        redact_details=True,
    )


def _error_partial(request: Request, message: str, request_id: str) -> HTMLResponse:
    ctx: dict[str, object] = {
        "request": request,
        "error": redact_html(message),
        "request_id": request_id,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/error_banner.html", ctx, status_code=404,
    )


def _success_partial(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "console/components/approval_success.html",
        {"request": request, "message": message, "menu": _menu_items()},
    )


# ─── Main list page ──────────────────────────────────────────────────────────


@approval_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def approval_page(
    request: Request,
    status: str = Query(""),
    risk: str = Query(""),
    q: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    stats = _approval_stats(CONSOLE_WORKSPACE_ID)

    items = _list_approvals(CONSOLE_WORKSPACE_ID, status, risk, q)
    items = [_redact_item(i) for i in items]

    ctx: dict[str, object] = {
        "request": request,
        "title": "Approvals",
        "version": "0.8.0-dev",
        "stats": stats,
        "status": status,
        "risk": risk,
        "q": q,
        "items": items,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/approval.html", ctx)


# ─── Detail page ──────────────────────────────────────────────────────────────


@approval_router.get("/{approval_id}", response_class=HTMLResponse, include_in_schema=False)
async def approval_detail(request: Request, approval_id: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    from cogito_agent.storage.repositories import ApprovalRepository

    db = _get_db()
    repo = ApprovalRepository(db)
    item = repo.get_by_id(approval_id)
    if item is None:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Approval '{approval_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)

    item = _redact_item(item)
    ctx = {
        "request": request,
        "title": "Approval Detail",
        "version": "0.8.0-dev",
        "item": item,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/approval_detail.html", ctx)


# ─── Actions: Approve / Reject ────────────────────────────────────────────────


@approval_router.post(
    "/{approval_id}/approve",
    response_class=HTMLResponse, include_in_schema=False,
)
async def approval_approve(
    request: Request,
    approval_id: str,
    reason: str = Form(""),
) -> HTMLResponse:
    from cogito_agent.storage.repositories import ApprovalRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = ApprovalRepository(db)

    result = repo.resolve(approval_id, "approved", CONSOLE_ACTOR)
    if result is None:
        existing = repo.get_by_id(approval_id)
        if existing is None:
            return _error_partial(request, "Approval not found", rid)
        msg = f"Approval already processed (status: {existing.get('status', 'unknown')})"
        return _error_partial(request, msg, rid)

    _audit_log(
        CONSOLE_ACTOR, "approval.approve",
        f"approval:{approval_id}", CONSOLE_WORKSPACE_ID,
        details={
            "operation": "approve",
            "approval_id": approval_id,
            "capability": result.get("capability_name", ""),
            "resource": result.get("resource", ""),
            "reason": reason,
            "decision_before": "pending",
            "decision_after": "approved",
        },
        request_id=rid,
    )
    return _success_partial(request, "Approval approved.")


@approval_router.post(
    "/{approval_id}/reject",
    response_class=HTMLResponse, include_in_schema=False,
)
async def approval_reject(
    request: Request,
    approval_id: str,
    reason: str = Form(""),
) -> HTMLResponse:
    from cogito_agent.storage.repositories import ApprovalRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = ApprovalRepository(db)

    result = repo.resolve(approval_id, "rejected", CONSOLE_ACTOR)
    if result is None:
        existing = repo.get_by_id(approval_id)
        if existing is None:
            return _error_partial(request, "Approval not found", rid)
        msg = f"Approval already processed (status: {existing.get('status', 'unknown')})"
        return _error_partial(request, msg, rid)

    _audit_log(
        CONSOLE_ACTOR, "approval.reject",
        f"approval:{approval_id}", CONSOLE_WORKSPACE_ID,
        details={
            "operation": "reject",
            "approval_id": approval_id,
            "capability": result.get("capability_name", ""),
            "resource": result.get("resource", ""),
            "reason": reason,
            "decision_before": "pending",
            "decision_after": "rejected",
        },
        request_id=rid,
    )
    return _success_partial(request, "Approval rejected.")
