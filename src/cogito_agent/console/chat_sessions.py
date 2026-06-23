from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.application import SessionApplicationService, WorkspaceApplicationService
from cogito_agent.console.context import MenuItem
from cogito_agent.console.services import ChatWorkspaceService

router = APIRouter()
HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

CONSOLE_WORKSPACE_ID = "default"


def _get_db_and_repos() -> tuple[Any, Any, Any, Any]:
    from cogito_agent.storage import get_db
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
    from cogito_agent.storage import get_db

    del ws_repo
    return WorkspaceApplicationService(get_db()).ensure_workspace(CONSOLE_WORKSPACE_ID)


def _session_commands() -> SessionApplicationService:
    from cogito_agent.storage import get_db

    return SessionApplicationService(get_db())


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
        request,
        "console/components/chat_sessions.html",
        ctx,
    )


@router.post("/chat/sessions", response_class=HTMLResponse)
async def create_session(request: Request) -> HTMLResponse:
    _db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    sess = _session_commands().create(CONSOLE_WORKSPACE_ID)

    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(sess),
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request,
        "console/components/chat_session_item.html",
        ctx,
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
    result = ChatWorkspaceService(db).get_messages(CONSOLE_WORKSPACE_ID, session_id, page=page)
    if result is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "error": "Session not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(
            request,
            "console/components/error_banner.html",
            error_ctx,
            status_code=404,
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
        request,
        "console/components/chat_history.html",
        ctx,
    )


@router.post("/chat/sessions/{session_id}/rename", response_class=HTMLResponse)
async def rename_session(request: Request, session_id: str, title: str = Form(...)) -> HTMLResponse:
    _db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    session = _session_commands().rename(CONSOLE_WORKSPACE_ID, session_id, title)
    if session is None:
        return HTMLResponse("Invalid session or title", status_code=422)
    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(session),
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/components/chat_session_item.html", ctx)


@router.post("/chat/sessions/{session_id}/branch", response_class=HTMLResponse)
async def branch_session(request: Request, session_id: str) -> HTMLResponse:
    _db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    session = _session_commands().branch(CONSOLE_WORKSPACE_ID, session_id)
    if session is None:
        return HTMLResponse("Session not found", status_code=404)
    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(session),
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/components/chat_session_item.html", ctx)


@router.get("/chat/turns/{trace_id}", response_class=HTMLResponse)
async def turn_inspector(request: Request, trace_id: str) -> HTMLResponse:
    db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    inspector = ChatWorkspaceService(db).get_turn_inspector(CONSOLE_WORKSPACE_ID, trace_id)
    if inspector is None:
        return HTMLResponse("Turn not found", status_code=404)
    return templates.TemplateResponse(
        request,
        "console/components/chat_turn_inspector.html",
        {"request": request, "inspector": inspector, "menu": _menu_items()},
    )


@router.post("/chat/sessions/{session_id}/archive", response_class=HTMLResponse)
async def archive_session(request: Request, session_id: str) -> HTMLResponse:
    _db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    if not _session_commands().archive(CONSOLE_WORKSPACE_ID, session_id):
        error_ctx: dict[str, object] = {
            "request": request,
            "error": "Session not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(
            request,
            "console/components/error_banner.html",
            error_ctx,
            status_code=404,
        )

    return HTMLResponse("")


@router.post("/chat/sessions/{session_id}/delete", response_class=HTMLResponse)
async def delete_session(request: Request, session_id: str) -> HTMLResponse:
    _db, ws_repo, _sess_repo, _msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    if not _session_commands().delete(CONSOLE_WORKSPACE_ID, session_id):
        error_ctx: dict[str, object] = {
            "request": request,
            "error": "Session not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(
            request,
            "console/components/error_banner.html",
            error_ctx,
            status_code=404,
        )

    return HTMLResponse("")
