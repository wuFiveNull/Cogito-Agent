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

memory_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"


# ─── helpers ─────────────────────────────────────────────────────────────────


def _get_db() -> _Database:
    from cogito_agent.api.app import get_db as _get_shared_db

    return _get_shared_db()


def _mem_stats(workspace_id: str) -> dict[str, int]:
    db = _get_db()
    sql_total = "SELECT COUNT(*) FROM memories WHERE workspace_id=? AND deleted_at IS NULL"
    sql_pending = (
        "SELECT COUNT(*) FROM memory_candidates WHERE"
        " workspace_id=? AND status='pending'"
    )
    sql_active = (
        "SELECT COUNT(*) FROM memories WHERE workspace_id=?"
        " AND deleted_at IS NULL AND status='active'"
    )
    sql_archived = (
        "SELECT COUNT(*) FROM memories WHERE workspace_id=?"
        " AND archived_at IS NOT NULL AND deleted_at IS NULL"
    )
    sql_stale = (
        "SELECT COUNT(*) FROM memories WHERE workspace_id=?"
        " AND status='stale'"
    )
    cur = db.connection
    total = cur.execute(sql_total, (workspace_id,)).fetchone()[0]
    pending = cur.execute(sql_pending, (workspace_id,)).fetchone()[0]
    accepted = cur.execute(sql_active, (workspace_id,)).fetchone()[0]
    archived = cur.execute(sql_archived, (workspace_id,)).fetchone()[0]
    stale = cur.execute(sql_stale, (workspace_id,)).fetchone()[0]
    return {
        "total": total,
        "pending": pending,
        "accepted": accepted,
        "archived": archived,
        "stale": stale,
    }


def _ensure_workspace(workspace_id: str) -> None:
    from cogito_agent.storage.repositories import WorkspaceRepository

    db = _get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(workspace_id)
    if ws is None:
        repo.create(workspace_id, workspace_id)


def _list_candidates(
    workspace_id: str,
    status: str = "",
    type_: str = "",
    q: str = "",
) -> list[dict[str, object]]:
    db = _get_db()
    sql = "SELECT * FROM memory_candidates WHERE workspace_id=?"
    params: list[Any] = [workspace_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    if type_:
        sql += " AND type=?"
        params.append(type_)
    if q:
        sql += " AND (text LIKE ? OR reason LIKE ?)"
        like = f"%{q}%"
        params.append(like)
        params.append(like)
    sql += " ORDER BY created_at DESC"
    rows = db.connection.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _list_memories(
    workspace_id: str,
    status: str = "",
    type_: str = "",
    q: str = "",
    archived_filter: str = "",
) -> list[dict[str, object]]:
    db = _get_db()
    sql = "SELECT * FROM memories WHERE workspace_id=? AND deleted_at IS NULL"
    params: list[Any] = [workspace_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    if type_:
        sql += " AND type=?"
        params.append(type_)
    if archived_filter == "no":
        sql += " AND archived_at IS NULL"
    elif archived_filter == "yes":
        sql += " AND archived_at IS NOT NULL"
    if q:
        sql += " AND (text LIKE ? OR summary LIKE ?)"
        like = f"%{q}%"
        params.append(like)
        params.append(like)
    sql += " ORDER BY created_at DESC"
    rows = db.connection.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _get_memory_or_candidate(
    id: str, workspace_id: str
) -> tuple[dict[str, object] | None, str]:
    db = _get_db()
    sql = "SELECT * FROM memories WHERE id=? AND workspace_id=?"
    cur = db.connection.execute(sql, (id, workspace_id))
    row = cur.fetchone()
    if row:
        return dict(row), "memory"
    cur = db.connection.execute("SELECT * FROM memory_candidates WHERE id=?", (id,))
    row = cur.fetchone()
    if row:
        return dict(row), "candidate"
    return None, ""


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


# ─── Main list page ──────────────────────────────────────────────────────────


@memory_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def memory_page(
    request: Request,
    tab: str = Query("all"),
    status: str = Query(""),
    type: str = Query(""),
    q: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    stats = _mem_stats(CONSOLE_WORKSPACE_ID)

    items: list[dict[str, object]] = []
    is_candidate_map: dict[str, bool] = {}

    if tab in ("all", "candidates"):
        cands = _list_candidates(CONSOLE_WORKSPACE_ID, status, type, q)
        for c in cands:
            items.append(_redact_item(c))
            is_candidate_map[str(c.get("id", ""))] = True

    if tab in ("all", "memories"):
        mems = _list_memories(CONSOLE_WORKSPACE_ID, status, type, q)
        for m in mems:
            items.append(_redact_item(m))
            is_candidate_map[str(m.get("id", ""))] = False

    if tab == "all":
        items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)

    ctx: dict[str, object] = {
        "request": request,
        "title": "Memory",
        "version": "0.8.0",
        "stats": stats,
        "tab": tab,
        "status": status,
        "type": type,
        "q": q,
        "items": items,
        "is_candidate": is_candidate_map,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/memory.html", ctx)


# ─── Detail page ─────────────────────────────────────────────────────────────


@memory_router.get("/{id}", response_class=HTMLResponse, include_in_schema=False)
async def memory_detail(request: Request, id: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    item, item_type = _get_memory_or_candidate(id, CONSOLE_WORKSPACE_ID)
    if item is None:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Memory or candidate '{id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)

    item = _redact_item(item)
    ctx = {
        "request": request,
        "title": "Memory Detail",
        "version": "0.8.0",
        "item": item,
        "item_type": item_type,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/memory_detail.html", ctx)


# ─── Actions: Candidates ─────────────────────────────────────────────────────


@memory_router.post(
    "/candidates/{candidate_id}/accept",
    response_class=HTMLResponse, include_in_schema=False,
)
async def candidate_accept(request: Request, candidate_id: str) -> HTMLResponse:
    from cogito_agent.storage.repositories import MemoryCandidateRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = MemoryCandidateRepository(db)
    result = repo.accept(candidate_id)
    if result is None:
        return _error_partial(request, "Candidate not found", rid)
    _audit_log(
        CONSOLE_ACTOR, "memory.accept", f"candidate:{candidate_id}",
        CONSOLE_WORKSPACE_ID, request_id=rid,
    )
    return templates.TemplateResponse(
        request, "console/components/memory_success.html",
        {"request": request, "message": "Candidate accepted.", "menu": _menu_items()},
    )


@memory_router.post(
    "/candidates/{candidate_id}/reject",
    response_class=HTMLResponse, include_in_schema=False,
)
async def candidate_reject(request: Request, candidate_id: str) -> HTMLResponse:
    from cogito_agent.storage.repositories import MemoryCandidateRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = MemoryCandidateRepository(db)
    result = repo.reject(candidate_id)
    if result is None:
        return _error_partial(request, "Candidate not found", rid)
    _audit_log(
        CONSOLE_ACTOR, "memory.reject", f"candidate:{candidate_id}",
        CONSOLE_WORKSPACE_ID, request_id=rid,
    )
    return templates.TemplateResponse(
        request, "console/components/memory_success.html",
        {"request": request, "message": "Candidate rejected.", "menu": _menu_items()},
    )


@memory_router.post(
    "/candidates/{candidate_id}/edit",
    response_class=HTMLResponse, include_in_schema=False,
)
async def candidate_edit(
    request: Request, candidate_id: str,
    text: str = Form(...),
    type: str = Form("general"),
    confidence: float = Form(0.5),
) -> HTMLResponse:
    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    old_row = db.connection.execute(
        "SELECT * FROM memory_candidates WHERE id=?", (candidate_id,)
    ).fetchone()
    if old_row is None:
        return _error_partial(request, "Candidate not found", rid)
    db.connection.execute(
        "UPDATE memory_candidates SET text=?, type=?, confidence=? WHERE id=?",
        (text, type, confidence, candidate_id),
    )
    db.connection.commit()
    _audit_log(
        CONSOLE_ACTOR, "memory.candidate.edit",
        f"candidate:{candidate_id}", CONSOLE_WORKSPACE_ID,
        details={"before_text_preview": str(old_row["text"])[:80], "after_text_preview": text[:80]},
        request_id=rid,
    )
    return templates.TemplateResponse(
        request, "console/components/memory_success.html",
        {"request": request, "message": "Candidate updated.", "menu": _menu_items()},
    )


# ─── Actions: Memories ───────────────────────────────────────────────────────


@memory_router.post("/{memory_id}/edit", response_class=HTMLResponse, include_in_schema=False)
async def memory_edit(
    request: Request, memory_id: str,
    text: str = Form(...),
) -> HTMLResponse:
    from cogito_agent.storage.repositories import MemoryRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = MemoryRepository(db)
    old = repo.get_by_id(memory_id, CONSOLE_WORKSPACE_ID)
    if old is None:
        return _error_partial(request, "Memory not found", rid)
    ok = repo.edit_text(memory_id, CONSOLE_WORKSPACE_ID, text, actor_id=CONSOLE_ACTOR)
    if not ok:
        return _error_partial(request, "Failed to update memory", rid)
    _audit_log(
        CONSOLE_ACTOR, "memory.edit",
        f"memory:{memory_id}", CONSOLE_WORKSPACE_ID,
        details={"before_text_preview": str(old["text"])[:80], "after_text_preview": text[:80]},
        request_id=rid,
    )
    return templates.TemplateResponse(
        request, "console/components/memory_success.html",
        {"request": request, "message": "Memory updated.", "menu": _menu_items()},
    )


@memory_router.post("/{memory_id}/archive", response_class=HTMLResponse, include_in_schema=False)
async def memory_archive(request: Request, memory_id: str) -> HTMLResponse:
    from cogito_agent.storage.repositories import MemoryRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = MemoryRepository(db)
    ok = repo.archive(memory_id, CONSOLE_WORKSPACE_ID)
    if not ok:
        return _error_partial(request, "Memory not found or already archived", rid)
    _audit_log(
        CONSOLE_ACTOR, "memory.archive", f"memory:{memory_id}",
        CONSOLE_WORKSPACE_ID, request_id=rid,
    )
    return templates.TemplateResponse(
        request, "console/components/memory_success.html",
        {"request": request, "message": "Memory archived.", "menu": _menu_items()},
    )


@memory_router.post("/{memory_id}/delete", response_class=HTMLResponse, include_in_schema=False)
async def memory_delete(request: Request, memory_id: str) -> HTMLResponse:
    from cogito_agent.storage.repositories import MemoryRepository

    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    repo = MemoryRepository(db)
    old = repo.get_by_id(memory_id, CONSOLE_WORKSPACE_ID)
    if old is None:
        return _error_partial(request, "Memory not found", rid)
    repo.soft_delete(memory_id, CONSOLE_WORKSPACE_ID)
    _audit_log(
        CONSOLE_ACTOR, "memory.delete",
        f"memory:{memory_id}", CONSOLE_WORKSPACE_ID,
        details={"text_preview": str(old["text"])[:80]},
        request_id=rid,
    )
    return templates.TemplateResponse(
        request, "console/components/memory_success.html",
        {"request": request, "message": "Memory deleted.", "menu": _menu_items()},
    )


# ─── Shared ──────────────────────────────────────────────────────────────────

CONSOLE_ACTOR = "console"


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
