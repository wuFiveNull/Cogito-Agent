from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .redaction import redact_html

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


def _menu_items() -> list[dict[str, str | bool]]:
    from .utils import menu_items
    return menu_items()


@router.get("/chat/sessions", response_class=HTMLResponse)
async def list_sessions(request: Request) -> HTMLResponse:
    db, ws_repo, sess_repo, msg_repo = _get_db_and_repos()
    _ensure_workspace(ws_repo)
    sessions_raw = sess_repo.list_by_workspace(CONSOLE_WORKSPACE_ID)
    session_list = []
    for s in sessions_raw:
        sid = str(s["id"])
        msgs = msg_repo.list_by_session(sid, CONSOLE_WORKSPACE_ID)
        last_msg = msgs[-1] if msgs else None
        session_list.append({
            "id": sid,
            "title": str(s.get("title", "")),
            "created_at": str(s.get("created_at", "")),
            "updated_at": str(s.get("updated_at", "")),
            "message_count": len(msgs),
            "last_preview": str(last_msg.get("content", ""))[:60] if last_msg else "",
        })

    ctx: dict[str, object] = {
        "request": request,
        "sessions": session_list,
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
async def get_session(request: Request, session_id: str) -> HTMLResponse:
    db, ws_repo, sess_repo, msg_repo = _get_db_and_repos()
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

    msgs = msg_repo.list_by_session(session_id, CONSOLE_WORKSPACE_ID)
    messages = []
    for m in msgs:
        messages.append({
            "id": str(m["id"]),
            "role": str(m["role"]),
            "content": redact_html(str(m.get("content", ""))),
            "created_at": str(m.get("created_at", "")),
        })

    ctx: dict[str, object] = {
        "request": request,
        "session": _session_to_json(sess),
        "messages": messages,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(
        request, "console/components/chat_history.html", ctx,
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
