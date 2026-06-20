from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.console.context import MenuItem
from cogito_agent.console.services import ChatWorkspaceService

router = APIRouter()
HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

CONSOLE_WORKSPACE_ID = "default"


def _get_db_and_repos() -> tuple[Any, Any, Any, Any]:
    from cogito_agent.api.app import get_db
    from cogito_agent.storage.repositories import (
        MessageRepository,
        SessionRepository,
        WorkspaceRepository,
    )
    db = get_db()
    ws_repo = WorkspaceRepository(db)
    sess_repo = SessionRepository(db)
    msg_repo = MessageRepository(db)
    return db, ws_repo, sess_repo, msg_repo


def _ensure_workspace(ws_repo: Any) -> dict[str, object]:
    ws: dict[str, object] | None = ws_repo.get_by_id(CONSOLE_WORKSPACE_ID)
    if ws is None:
        ws = cast("dict[str, object]", ws_repo.create(CONSOLE_WORKSPACE_ID, CONSOLE_WORKSPACE_ID))
    return ws


def _audit_log(
    db: Any,
    actor_id: str,
    action: str,
    resource: str,
    workspace_id: str,
    session_id: str = "",
    details: str = "{}",
) -> None:
    from cogito_agent.governance.audit import AuditLogger
    AuditLogger(db).log(
        actor_id=actor_id,
        action=action,
        resource=resource,
        workspace_id=workspace_id,
        session_id=session_id,
        decision="allow",
        reason="console session management",
        details=details,
    )


def _session_to_json(s: dict[str, object]) -> dict[str, object]:
    return {
        "id": s["id"],
        "workspace_id": s["workspace_id"],
        "title": s.get("title", ""),
        "status": s.get("status", "active"),
        "created_at": s.get("created_at", ""),
        "updated_at": s.get("updated_at", ""),
    }


def _menu_items() -> list[MenuItem]:
    from .utils import menu_items
    return menu_items()


@router.get("/chat/sessions", response_class=HTMLResponse)
async def list_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
) -> HTMLResponse:
    db, ws_repo, sess_repo, msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    del sess_repo, msg_repo
    result = ChatWorkspaceService(db).list_sessions(
        CONSOLE_WORKSPACE_ID, page=page, page_size=page_size
    )

    ctx: dict[str, object] = {
        "request": request,
        "sessions": result["items"],
        "has_more": result["has_more"],
        "next_page": page + 1,
        "append_page": page > 1,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/chat_sessions.html", ctx,
    )


@router.post("/chat/sessions", response_class=HTMLResponse)
async def create_session(request: Request) -> HTMLResponse:
    db, ws_repo, sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    sid = str(uuid.uuid4())
    sess = sess_repo.create(sid, CONSOLE_WORKSPACE_ID, "New Chat")
    _audit_log(db, "user", "session_created", "session", CONSOLE_WORKSPACE_ID, sid)

    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(sess),
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/chat_session_item.html", ctx,
    )


@router.get("/chat/sessions/{session_id}", response_class=HTMLResponse)
async def get_session(
    request: Request,
    session_id: str,
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    db, ws_repo, sess_repo, msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    del sess_repo, msg_repo
    result = ChatWorkspaceService(db).get_messages(
        CONSOLE_WORKSPACE_ID, session_id, page=page
    )
    if result is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "error": "Session not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(
            request, "console/components/error_banner.html", error_ctx, status_code=404,
        )

    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(cast("dict[str, object]", result["session"])),
        "messages": result["messages"],
        "has_older": result["has_older"],
        "next_page": page + 1,
        "last_user_message": result["last_user_message"],
        "workspace_id": CONSOLE_WORKSPACE_ID,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/chat_history.html", ctx,
    )


@router.post("/chat/sessions/{session_id}/rename", response_class=HTMLResponse)
async def rename_session(
    request: Request, session_id: str, title: str = Form(...)
) -> HTMLResponse:
    db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    session = ChatWorkspaceService(db).rename_session(
        CONSOLE_WORKSPACE_ID, session_id, title
    )
    if session is None:
        return HTMLResponse("Invalid session or title", status_code=422)
    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(session),
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/chat_session_item.html", ctx
    )


@router.post("/chat/sessions/{session_id}/branch", response_class=HTMLResponse)
async def branch_session(request: Request, session_id: str) -> HTMLResponse:
    db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    session = ChatWorkspaceService(db).branch_session(
        CONSOLE_WORKSPACE_ID, session_id
    )
    if session is None:
        return HTMLResponse("Session not found", status_code=404)
    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(session),
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/chat_session_item.html", ctx
    )


@router.get("/chat/turns/{trace_id}", response_class=HTMLResponse)
async def turn_inspector(request: Request, trace_id: str) -> HTMLResponse:
    db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    inspector = ChatWorkspaceService(db).get_turn_inspector(
        CONSOLE_WORKSPACE_ID, trace_id
    )
    if inspector is None:
        return HTMLResponse("Turn not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "console/components/chat_turn_inspector.html",
        {"request": request, "inspector": inspector, "menu": _menu_items()},
    )


@router.post("/chat/sessions/{session_id}/archive", response_class=HTMLResponse)
async def archive_session(request: Request, session_id: str) -> HTMLResponse:
    db, ws_repo, sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    sess = sess_repo.get_by_id(session_id, CONSOLE_WORKSPACE_ID)
    if sess is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "error": "Session not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(
            request, "console/components/error_banner.html", error_ctx, status_code=404,
        )

    sess_repo.soft_delete(session_id, CONSOLE_WORKSPACE_ID)
    _audit_log(db, "user", "session_archived", "session", CONSOLE_WORKSPACE_ID, session_id)
    return HTMLResponse("")


@router.post("/chat/sessions/{session_id}/delete", response_class=HTMLResponse)
async def delete_session(request: Request, session_id: str) -> HTMLResponse:
    db, ws_repo, sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    sess = sess_repo.get_by_id(session_id, CONSOLE_WORKSPACE_ID)
    if sess is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "error": "Session not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(
            request, "console/components/error_banner.html", error_ctx, status_code=404,
        )

    sess_repo.hard_delete(session_id, CONSOLE_WORKSPACE_ID)
    _audit_log(db, "user", "session_deleted", "session", CONSOLE_WORKSPACE_ID, session_id)
    return HTMLResponse("")
