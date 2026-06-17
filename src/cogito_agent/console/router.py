from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .approval import approval_router as _approval_router
from .audit_views import audit_router as _audit_router
from .autonomy_views import autonomy_router as _autonomy_router
from .chat_sessions import router as _chat_sessions_router
from .config_views import config_router as _config_router
from .doctor_views import doctor_router as _doctor_router
from .memory import memory_router as _memory_router
from .redaction import redact_html
from .status import build_status
from .trace_views import trace_router as _trace_router
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

console_router = APIRouter()

CONSOLE_SESSION_ID = "console-default"
CONSOLE_WORKSPACE_ID = "default"


def _ensure_console_session() -> str:
    from cogito_agent.storage import Database
    from cogito_agent.storage.repositories import SessionRepository

    db = Database()
    db.initialize()
    db.migrate()
    repo = SessionRepository(db)
    sess = repo.get_by_id(CONSOLE_SESSION_ID, CONSOLE_WORKSPACE_ID)
    if sess is None:
        from cogito_agent.storage.repositories import WorkspaceRepository

        ws_repo = WorkspaceRepository(db)
        ws = ws_repo.get_by_id(CONSOLE_WORKSPACE_ID)
        if ws is None:
            ws = ws_repo.create(CONSOLE_WORKSPACE_ID, CONSOLE_WORKSPACE_ID)
        repo.create(CONSOLE_SESSION_ID, CONSOLE_WORKSPACE_ID, "Console Chat")
    return CONSOLE_SESSION_ID


# ─── Dashboard ──────────────────────────────────────────────────────────────


@console_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    status_data = build_status()
    stats = status_data.get("counts", {})
    ctx: dict[str, object] = {
        "request": request,
        "title": "Dashboard",
        "version": status_data.get("version", "0.0.0"),
        "status": status_data,
        "stats": stats,
        "menu": _menu_items(),
        "limitations": status_data.get("limitations", []),
    }
    return templates.TemplateResponse(request, "console/dashboard.html", ctx)


# ─── Chat Page ──────────────────────────────────────────────────────────────


@console_router.get("/chat", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(request: Request) -> HTMLResponse:
    from cogito_agent.storage import Database
    from cogito_agent.storage.repositories import (
        MessageRepository,
        SessionRepository,
        WorkspaceRepository,
    )

    _ensure_console_session()

    db = Database()
    db.initialize()
    db.migrate()
    sess_repo = SessionRepository(db)
    msg_repo = MessageRepository(db)
    ws_repo = WorkspaceRepository(db)
    ws_repo.get_by_id(CONSOLE_WORKSPACE_ID)

    sessions_raw = sess_repo.list_by_workspace(CONSOLE_WORKSPACE_ID)
    session_list = []
    for s in sessions_raw:
        sd: dict[str, object] = dict(s)
        sid = str(sd["id"])
        msgs = msg_repo.list_by_session(sid, CONSOLE_WORKSPACE_ID)
        last_msg = msgs[-1] if msgs else None
        session_list.append({
            "id": sid,
            "title": str(sd.get("title", "")),
            "created_at": str(sd.get("created_at", "")),
            "updated_at": str(sd.get("updated_at", "")),
            "message_count": len(msgs),
            "last_preview": str(last_msg.get("content", ""))[:60] if last_msg else "",
        })

    ctx: dict[str, object] = {
        "request": request,
        "title": "Chat",
        "version": "0.9.0-dev",
        "session_id": CONSOLE_SESSION_ID,
        "workspace_id": CONSOLE_WORKSPACE_ID,
        "sessions": session_list,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/chat.html", ctx)


# ─── Chat Send (non-streaming) ──────────────────────────────────────────────


@console_router.post("/chat/send", response_class=HTMLResponse, include_in_schema=False)
async def chat_send(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(CONSOLE_SESSION_ID),
    workspace_id: str = Form(CONSOLE_WORKSPACE_ID),
) -> HTMLResponse:
    from cogito_agent.api.app import get_db, get_kernel
    from cogito_agent.shared import EventSource, EventType, RuntimeEvent

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    message = message.strip()
    if not message:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Chat",
            "error": "Message cannot be empty.",
            "session_id": session_id,
            "workspace_id": workspace_id,
        }
        return templates.TemplateResponse(
            request, "console/components/error_banner.html", ctx, status_code=422
        )

    try:
        db = get_db()
        kernel = get_kernel()

        from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository

        ws_repo = WorkspaceRepository(db)
        ws = ws_repo.get_by_id(workspace_id)
        if ws is None:
            ws = ws_repo.create(workspace_id, workspace_id)

        sess_repo = SessionRepository(db)
        sess = sess_repo.get_by_id(session_id, workspace_id)
        if sess is None:
            sess = sess_repo.create(session_id, workspace_id, "Console Chat")

        event = RuntimeEvent(
            workspace_id=workspace_id,
            session_id=session_id,
            actor_id="user",
            source=EventSource.api,
            type=EventType.user_message,
            payload={"text": message, "_request_id": rid},
        )

        result = kernel.process(event)
        output = redact_html(result.output or "")
        trace_id = redact_html(result.trace_id or "")
        state = str(result.state.value) if hasattr(result.state, "value") else str(result.state)

        ctx = {
            "request": request,
            "title": "Chat",
            "user_message": redact_html(message),
            "assistant_message": output,
            "trace_id": trace_id,
            "request_id": rid,
            "state": state,
            "session_id": session_id,
            "workspace_id": workspace_id,
        }
        return templates.TemplateResponse(request, "console/components/chat_message.html", ctx)

    except Exception as exc:
        logger.exception("chat_send error")
        safe_error = redact_html(str(exc))
        ctx = {
            "request": request,
            "title": "Chat",
            "error": safe_error,
            "request_id": rid,
            "session_id": session_id,
            "workspace_id": workspace_id,
        }
        return templates.TemplateResponse(
            request, "console/components/error_banner.html", ctx, status_code=500
        )


# ─── Chat Stream (SSE) ──────────────────────────────────────────────────────


@console_router.post("/chat/stream", include_in_schema=False)
async def chat_stream_route(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(CONSOLE_SESSION_ID),
    workspace_id: str = Form(CONSOLE_WORKSPACE_ID),
) -> StreamingResponse:
    from cogito_agent.api.app import get_db, get_kernel
    from cogito_agent.cli.config_manager import get_config
    from cogito_agent.shared import EventSource, EventType, RuntimeEvent, StreamEventType
    from cogito_agent.trace.redaction import RedactionHelper

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    message = message.strip()
    redactor = RedactionHelper()

    def event_stream() -> Any:
        try:
            db = get_db()
            kernel = get_kernel()

            from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository

            ws_repo = WorkspaceRepository(db)
            ws = ws_repo.get_by_id(workspace_id)
            if ws is None:
                ws = ws_repo.create(workspace_id, workspace_id)

            sess_repo = SessionRepository(db)
            sess = sess_repo.get_by_id(session_id, workspace_id)
            if sess is None:
                sess = sess_repo.create(session_id, workspace_id, "Console Chat")

            event = RuntimeEvent(
                workspace_id=workspace_id,
                session_id=session_id,
                actor_id="user",
                source=EventSource.api,
                type=EventType.user_message,
                payload={"text": message, "_request_id": rid, "channel": "console_stream"},
            )

            cfg = get_config()
            streaming_enabled = cfg.get("model.streaming_enabled", "true").lower() == "true"
            max_retries = int(cfg.get("model.max_retries", "2"))

            for sev in kernel.process_stream(
                event,
                request_id=rid,
                streaming_enabled=streaming_enabled,
                max_retries=max_retries,
            ):
                if sev.type == StreamEventType.delta:
                    sev.data["delta"] = redactor.redact(str(sev.data.get("delta", "")))
                elif sev.type == StreamEventType.error:
                    err = sev.data.get("error", {})
                    if isinstance(err, dict):
                        err["message"] = redactor.redact(str(err.get("message", "")))
                        sev.data["error"] = err
                elif sev.type == StreamEventType.approval_required:
                    sev.data["summary"] = redactor.redact(str(sev.data.get("summary", "")))
                elif sev.type in (StreamEventType.final, StreamEventType.metadata):
                    for k, v in sev.data.items():
                        if isinstance(v, str):
                            sev.data[k] = redactor.redact(v)

                yield sev.to_sse()

        except Exception:
            logger.exception("chat_stream_route error")
            err_data = json.dumps({
                "error": {
                    "code": "STREAM_ERROR",
                    "message": "Stream error occurred",
                    "request_id": rid,
                    "retryable": False,
                }
            })
            yield f"event: error\ndata: {err_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


console_router.include_router(_memory_router, prefix="/memory")
console_router.include_router(_approval_router, prefix="/approval")
console_router.include_router(_chat_sessions_router, prefix="")
console_router.include_router(_trace_router, prefix="/traces")
console_router.include_router(_audit_router, prefix="/audit")
console_router.include_router(_autonomy_router, prefix="/autonomy")
console_router.include_router(_config_router, prefix="/config")
console_router.include_router(_doctor_router, prefix="/doctor")


# ─── Placeholder Pages ──────────────────────────────────────────────────────


PLACEHOLDER_PAGES: list[str] = []

_PHASE_MAP: dict[str, str] = {}


@console_router.get("/{page}", response_class=HTMLResponse, include_in_schema=False)
async def placeholder_page(request: Request, page: str) -> HTMLResponse:
    if page not in PLACEHOLDER_PAGES:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Page '{page}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)
    phase = _PHASE_MAP.get(page, "N")
    placeholder_ctx: dict[str, object] = {
        "request": request,
        "title": page.capitalize(),
        "page_name": page.capitalize(),
        "phase": phase,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/placeholder.html", placeholder_ctx)
