from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.version import APP_VERSION

from .approval import approval_router as _approval_router
from .artifact_views import artifact_router as _artifact_router
from .audit_views import audit_router as _audit_router
from .autonomy_views import autonomy_router as _autonomy_router
from .backup_views import backup_router as _backup_router
from .chat_sessions import router as _chat_sessions_router
from .config_views import config_router as _config_router
from .doctor_views import doctor_router as _doctor_router
from .drift_views import drift_router as _drift_router
from .inbox_views import inbox_router as _inbox_router
from .mcp_views import mcp_router as _mcp_router
from .memory import memory_router as _memory_router
from .redaction import redact_html
from .run_views import run_router as _run_router
from .services import ConsoleOverviewService, DashboardService
from .static_version import STATIC_VERSION
from .trace_views import trace_router as _trace_router
from .utils import csrf_token_input
from .utils import menu_items as _menu_items
from .workspace_views import workspace_files_router as _workspace_files_router

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals["static_version"] = STATIC_VERSION

console_router = APIRouter()

CONSOLE_SESSION_ID = "console-default"
CONSOLE_WORKSPACE_ID = "default"


def _ensure_console_session() -> str:
    from cogito_agent.storage import get_db
    from cogito_agent.storage.repositories import SessionRepository

    db = get_db()
    repo = SessionRepository(db)
    sess = repo.get_by_id(CONSOLE_SESSION_ID, CONSOLE_WORKSPACE_ID)
    if sess is None:
        # Check if session exists but is soft-deleted; restore it
        restored = repo.restore(CONSOLE_SESSION_ID, CONSOLE_WORKSPACE_ID)
        if restored:
            sess = restored
        else:
            from cogito_agent.application import WorkspaceApplicationService

            service = WorkspaceApplicationService(db)
            service.ensure_workspace(CONSOLE_WORKSPACE_ID)
            service.create_session(
                CONSOLE_WORKSPACE_ID,
                "Console Chat",
                session_id=CONSOLE_SESSION_ID,
                actor_id="console",
            )
    return CONSOLE_SESSION_ID


# ─── Dashboard ──────────────────────────────────────────────────────────────

_dashboard_service = DashboardService()
_overview_service = ConsoleOverviewService()


@console_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    status_data = _dashboard_service.get_system_status()
    stats = status_data.get("counts", {})
    limitations = status_data.get("limitations", [])
    ctx = cast(
        "dict[str, Any]",
        _dashboard_service.build_page_context(
            request,
            "Dashboard",
            extra={"status": status_data, "stats": stats, "limitations": limitations},
        ),
    )
    return templates.TemplateResponse(request, "console/dashboard.html", ctx)


@console_router.get("/overview", response_class=HTMLResponse, include_in_schema=False)
async def overview_page(request: Request) -> HTMLResponse:
    ctx = cast(
        "dict[str, Any]",
        _overview_service.build_page_context(request, "Overview"),
    )
    return templates.TemplateResponse(request, "console/overview.html", ctx)


# ─── Chat Page ──────────────────────────────────────────────────────────────


@console_router.get("/chat", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(request: Request) -> HTMLResponse:
    from cogito_agent.console.services import ChatWorkspaceService
    from cogito_agent.storage import get_db
    from cogito_agent.storage.repositories import (
        WorkspaceRepository,
    )

    _ensure_console_session()

    db = get_db()
    ws_repo = WorkspaceRepository(db)
    ws_repo.get_by_id(CONSOLE_WORKSPACE_ID)
    sessions = ChatWorkspaceService(db).list_sessions(CONSOLE_WORKSPACE_ID)

    csrf_val = getattr(request.state, "csrf_token", "")
    csrf_token_input_html = csrf_token_input(request)
    ctx: dict[str, object] = {
        "request": request,
        "title": "Chat",
        "version": APP_VERSION,
        "session_id": CONSOLE_SESSION_ID,
        "workspace_id": CONSOLE_WORKSPACE_ID,
        "sessions": sessions["items"],
        "has_more_sessions": sessions["has_more"],
        "menu": _menu_items(),
        "csrf_token": csrf_val,
        "csrf_token_input": csrf_token_input_html,
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
    from cogito_agent.api.app import get_chat_service
    from cogito_agent.shared import EventSource, EventType, RuntimeEvent
    from cogito_agent.storage import get_db

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
        chat_service = get_chat_service()

        from cogito_agent.application import WorkspaceApplicationService
        from cogito_agent.storage.repositories import SessionRepository

        workspace_service = WorkspaceApplicationService(db)
        workspace_service.ensure_workspace(workspace_id)

        sess_repo = SessionRepository(db)
        sess = sess_repo.get_by_id(session_id, workspace_id)
        if sess is None:
            workspace_service.create_session(
                workspace_id,
                "Console Chat",
                session_id=session_id,
                actor_id="console",
            )

        event = RuntimeEvent(
            workspace_id=workspace_id,
            session_id=session_id,
            actor_id="user",
            source=EventSource.api,
            type=EventType.user_message,
            payload={"text": message, "_request_id": rid},
        )

        result = chat_service.process(event)
        from cogito_agent.console.markdown import render_safe_markdown

        output = redact_html(result.output or "")
        trace_id = redact_html(result.trace_id or "")
        state = str(result.state.value) if hasattr(result.state, "value") else str(result.state)

        ctx = {
            "request": request,
            "title": "Chat",
            "user_message": redact_html(message),
            "assistant_message": output,
            "assistant_html": render_safe_markdown(result.output or ""),
            "tool_summaries": result.tool_summaries,
            "approval_pending": result.approval_pending,
            "approval_id": redact_html(result.approval_id or ""),
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
    from cogito_agent.api.app import get_chat_service
    from cogito_agent.cli.config_manager import get_config
    from cogito_agent.shared import EventSource, EventType, RuntimeEvent, StreamEventType
    from cogito_agent.storage import get_db
    from cogito_agent.shared.redaction import RedactionHelper

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    message = message.strip()
    redactor = RedactionHelper()

    def event_stream() -> Any:
        try:
            db = get_db()
            chat_service = get_chat_service()

            from cogito_agent.application import WorkspaceApplicationService
            from cogito_agent.storage.repositories import SessionRepository

            workspace_service = WorkspaceApplicationService(db)
            workspace_service.ensure_workspace(workspace_id)

            sess_repo = SessionRepository(db)
            sess = sess_repo.get_by_id(session_id, workspace_id)
            if sess is None:
                workspace_service.create_session(
                    workspace_id,
                    "Console Chat",
                    session_id=session_id,
                    actor_id="console",
                )

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

            for sev in chat_service.process_stream(
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
            err_data = json.dumps(
                {
                    "error": {
                        "code": "STREAM_ERROR",
                        "message": "Stream error occurred",
                        "request_id": rid,
                        "retryable": False,
                    }
                }
            )
            yield f"event: error\ndata: {err_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Chat Interrupt ────────────────────────────────────────────────────


@console_router.post("/chat/interrupt", include_in_schema=False)
async def chat_interrupt(
    request: Request,
    session_id: str = Form(CONSOLE_SESSION_ID),
    workspace_id: str = Form(CONSOLE_WORKSPACE_ID),
) -> HTMLResponse:
    from cogito_agent.api.app import get_chat_service
    from cogito_agent.shared import EventSource, EventType, RuntimeEvent

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    event = RuntimeEvent(
        workspace_id=workspace_id,
        session_id=session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_interrupt,
        payload={"text": "", "_request_id": rid},
    )
    chat_service = get_chat_service()
    chat_service.interrupt(event)
    return HTMLResponse(status_code=200, content="")


console_router.include_router(_memory_router, prefix="/memory")
console_router.include_router(_approval_router, prefix="/approval")
console_router.include_router(_run_router, prefix="/runs")
console_router.include_router(_mcp_router, prefix="/mcp")
console_router.include_router(_backup_router, prefix="/backups")
console_router.include_router(_chat_sessions_router, prefix="")
console_router.include_router(_trace_router, prefix="/traces")
console_router.include_router(_audit_router, prefix="/audit")
console_router.include_router(_autonomy_router, prefix="/autonomy")
console_router.include_router(_config_router, prefix="/config")
console_router.include_router(_drift_router, prefix="/drift")
console_router.include_router(_doctor_router, prefix="/doctor")
console_router.include_router(_inbox_router, prefix="/inbox")
console_router.include_router(_workspace_files_router, prefix="/workspace/files")
console_router.include_router(_artifact_router, prefix="/artifacts")


# ─── Console catch-all ──────────────────────────────────────────────────────


@console_router.get("/{page}", response_class=HTMLResponse, include_in_schema=False)
async def console_page_not_found(request: Request, page: str) -> HTMLResponse:
    csrf_val = getattr(request.state, "csrf_token", "")
    csrf_token_input_html = csrf_token_input(request)
    ctx: dict[str, object] = {
        "request": request,
        "title": "Not Found",
        "message": f"Page '{page}' not found.",
        "menu": _menu_items(),
        "csrf_token": csrf_val,
        "csrf_token_input": csrf_token_input_html,
    }
    return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)
