from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

autonomy_router = APIRouter()

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


# ─── Dashboard ────────────────────────────────────────────────────────────────


@autonomy_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def autonomy_dashboard(request: Request) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()

    from cogito_agent.autonomy import DecisionStore, FeedbackStore, Outbox
    from cogito_agent.governance import AuditLogger

    dstore = DecisionStore(db)
    obox = Outbox(db)
    fb = FeedbackStore(db, audit_logger=AuditLogger(db))

    action_counts = dstore.count_by_action(CONSOLE_WORKSPACE_ID)
    dec_24h = len(dstore.list_decisions_filtered(
        workspace_id=CONSOLE_WORKSPACE_ID, time_range="24h",
    ))

    status_counts = obox.count_by_status(CONSOLE_WORKSPACE_ID)
    fb_counts = fb.count_by_value(CONSOLE_WORKSPACE_ID)

    stats: dict[str, object] = {
        "decisions_total": sum(action_counts.values()),
        "decisions_24h": dec_24h,
        "push": action_counts.get("push", 0),
        "skip": action_counts.get("skip", 0),
        "defer": action_counts.get("defer", 0),
        "require_approval": action_counts.get("require_approval", 0),
        "outbox_pending": status_counts.get("pending", 0),
        "outbox_sent": status_counts.get("sent", 0),
        "outbox_failed": status_counts.get("failed", 0),
        "feedback_total": sum(fb_counts.values()),
        "feedback_useful": fb_counts.get("useful", 0),
        "feedback_too_many": fb_counts.get("too_many", 0),
        "feedback_wrong_time": fb_counts.get("wrong_time", 0),
    }

    ctx: dict[str, object] = {
        "request": request,
        "title": "Autonomy",
        "version": "0.8.0-dev",
        "stats": stats,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/autonomy.html", ctx)


# ─── Decisions List ───────────────────────────────────────────────────────────


@autonomy_router.get("/decisions", response_class=HTMLResponse, include_in_schema=False)
async def decisions_page(
    request: Request,
    action: str = Query(""),
    reason_code: str = Query(""),
    q: str = Query(""),
    time_range: str = Query("all"),
    workspace_id: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.autonomy import DecisionStore
    dstore = DecisionStore(db)

    ws = workspace_id or CONSOLE_WORKSPACE_ID
    items = dstore.list_decisions_filtered(
        workspace_id=ws, action=action, reason_code=reason_code,
        q=q, time_range=time_range, limit=200,
    )
    items = [_redact_item(i) for i in items]

    action_counts = dstore.count_by_action(ws)
    stats: dict[str, object] = {
        "total": sum(action_counts.values()),
        "push": action_counts.get("push", 0),
        "skip": action_counts.get("skip", 0),
        "defer": action_counts.get("defer", 0),
        "require_approval": action_counts.get("require_approval", 0),
    }

    ctx: dict[str, object] = {
        "request": request,
        "title": "Autonomy Decisions",
        "version": "0.8.0-dev",
        "stats": stats,
        "action": action,
        "reason_code": reason_code,
        "q": q,
        "time_range": time_range,
        "items": items,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/autonomy_decisions.html", ctx)


# ─── Decision Detail ──────────────────────────────────────────────────────────


@autonomy_router.get(
    "/decisions/{decision_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def decision_detail(request: Request, decision_id: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.autonomy import DecisionStore, FeedbackStore, Outbox
    from cogito_agent.governance import AuditLogger

    dstore = DecisionStore(db)
    decision = dstore.get_decision(decision_id)
    if decision is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Decision '{decision_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", error_ctx, status_code=404)

    decision = _redact_item(decision)

    ws_id = str(decision.get("workspace_id", "*") or "*")

    obox = Outbox(db)
    outbox_msgs = obox.list_messages_filtered(
        workspace_id=ws_id, q=decision_id, limit=10,
    )
    outbox_msgs = [_redact_item(m) for m in outbox_msgs]

    fb = FeedbackStore(db, audit_logger=AuditLogger(db))
    feedback_entries = fb.get_feedback_for_decision(decision_id)
    feedback_entries = [_redact_item(f) for f in feedback_entries]

    event_id = str(decision.get("event_id", ""))
    trace_id = str(decision.get("trace_id", ""))

    raw_json = json.dumps(decision, indent=2, default=str)
    raw_json = redact_html(raw_json)

    ctx: dict[str, object] = {
        "request": request,
        "title": "Decision Detail",
        "version": "0.8.0-dev",
        "decision": decision,
        "event_metadata_raw": "",
        "outbox_messages": outbox_msgs,
        "feedback_entries": feedback_entries,
        "event_id": event_id,
        "trace_id": trace_id,
        "raw_json": raw_json,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/autonomy_decision_detail.html", ctx)


# ─── Feedback for Decision ────────────────────────────────────────────────────


@autonomy_router.post(
    "/decisions/{decision_id}/feedback",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def decision_feedback(
    request: Request,
    decision_id: str,
    value: str = Form(...),
    comment: str = Form(""),
) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()

    from cogito_agent.autonomy import DecisionStore, FeedbackStore, FeedbackValue
    from cogito_agent.governance import AuditLogger

    dstore = DecisionStore(db)
    decision = dstore.get_decision(decision_id)
    if decision is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Decision '{decision_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", error_ctx, status_code=404)

    try:
        FeedbackValue(value)
    except ValueError:
        valid = [v.value for v in FeedbackValue]
        err_ctx: dict[str, object] = {
            "request": request,
            "title": "Invalid Feedback Value",
            "message": f"Invalid feedback value: '{value}'. Valid: {valid}",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", err_ctx, status_code=422)

    try:
        ws_id = str(decision.get("workspace_id", "*") or "*")
        fb = FeedbackStore(db, audit_logger=AuditLogger(db))
        fb.record_feedback(
            decision_id=decision_id,
            event_id=str(decision.get("event_id", "")),
            value=value,
            comment=comment,
            workspace_id=ws_id,
            trace_id=str(decision.get("trace_id", "")),
        )
    except Exception as exc:
        logger.exception("feedback record error")
        safe_error = redact_html(str(exc))
        err_ctx = {
            "request": request,
            "title": "Feedback Error",
            "message": safe_error,
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", err_ctx, status_code=500)

    return RedirectResponse(
        url=f"/console/autonomy/decisions/{decision_id}",
        status_code=303,
    )


# ─── Outbox List ──────────────────────────────────────────────────────────────


@autonomy_router.get("/outbox", response_class=HTMLResponse, include_in_schema=False)
async def outbox_page(
    request: Request,
    status: str = Query(""),
    q: str = Query(""),
    time_range: str = Query("all"),
    workspace_id: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.autonomy import Outbox

    obox = Outbox(db)
    ws = workspace_id or CONSOLE_WORKSPACE_ID
    items = obox.list_messages_filtered(
        workspace_id=ws, status=status, q=q, time_range=time_range, limit=200,
    )
    items = [_redact_item(i) for i in items]

    status_counts = obox.count_by_status(ws)
    stats: dict[str, object] = {
        "total": sum(status_counts.values()),
        "pending": status_counts.get("pending", 0),
        "sent": status_counts.get("sent", 0),
        "failed": status_counts.get("failed", 0),
    }

    ctx: dict[str, object] = {
        "request": request,
        "title": "Autonomy Outbox",
        "version": "0.8.0-dev",
        "stats": stats,
        "status": status,
        "q": q,
        "time_range": time_range,
        "items": items,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/autonomy_outbox.html", ctx)


# ─── Outbox Detail ────────────────────────────────────────────────────────────


@autonomy_router.get("/outbox/{message_id}", response_class=HTMLResponse, include_in_schema=False)
async def outbox_detail(request: Request, message_id: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.autonomy import Outbox

    obox = Outbox(db)
    msg = obox.get_message(message_id)
    if msg is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Outbox message '{message_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", error_ctx, status_code=404)

    msg = _redact_item(msg)
    raw_json = json.dumps(msg, indent=2, default=str)
    raw_json = redact_html(raw_json)

    ctx: dict[str, object] = {
        "request": request,
        "title": "Outbox Detail",
        "version": "0.8.0-dev",
        "msg": msg,
        "raw_json": raw_json,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/autonomy_outbox_detail.html", ctx)


# ─── Feedback List ────────────────────────────────────────────────────────────


@autonomy_router.get("/feedback", response_class=HTMLResponse, include_in_schema=False)
async def feedback_page(
    request: Request,
    value: str = Query(""),
    decision_id: str = Query(""),
    time_range: str = Query("all"),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.autonomy import FeedbackStore

    fb = FeedbackStore(db)
    items = fb.list_feedback(
        workspace_id=CONSOLE_WORKSPACE_ID,
        value=value, decision_id=decision_id, time_range=time_range, limit=200,
    )
    items = [_redact_item(i) for i in items]

    value_counts = fb.count_by_value(CONSOLE_WORKSPACE_ID)
    stats: dict[str, object] = {
        "total": sum(value_counts.values()),
        "useful": value_counts.get("useful", 0),
        "not_useful": value_counts.get("not_useful", 0),
        "too_many": value_counts.get("too_many", 0),
        "wrong_time": value_counts.get("wrong_time", 0),
        "irrelevant": value_counts.get("irrelevant", 0),
    }

    ctx: dict[str, object] = {
        "request": request,
        "title": "Autonomy Feedback",
        "version": "0.8.0-dev",
        "stats": stats,
        "value": value,
        "decision_id": decision_id,
        "time_range": time_range,
        "items": items,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/autonomy_feedback.html", ctx)
