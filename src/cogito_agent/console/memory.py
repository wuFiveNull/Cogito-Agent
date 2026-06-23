"""Console memory pages — Memory v2. Reads from memory_items + memories tables."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

memory_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"
CONSOLE_ACTOR = "console"


def _get_db():
    from cogito_agent.storage import get_db
    return get_db()



# ─── Stats ────────────────────────────────────────────────────────────


def _mem_stats(workspace_id: str) -> dict[str, int]:
    try:
        db = _get_db()
        from cogito_agent.storage.repositories import MemoryItemRepository, MemoryRepository
        v2_repo = MemoryItemRepository(db)
        old_repo = MemoryRepository(db)
        v2_count = v2_repo.count_active(workspace_id, exclude_type="_recent_context")
        old_count = old_repo.count_active(workspace_id)
        archived = old_repo.count_archived(workspace_id)
        return {
            "total": v2_count + old_count + archived,
            "pending": 0,
            "accepted": v2_count + old_count,
            "archived": archived,
            "stale": 0,
        }
    except Exception:
        return {"total": 0, "pending": 0, "accepted": 0, "archived": 0, "stale": 0}


# ─── List helpers (memory_items + memories tables) ────────────────────


def _list_all(
    workspace_id: str,
    type_: str = "",
    q: str = "",
    archived_filter: str = "",
) -> list[dict[str, object]]:
    """List memories from both memory_items (v2) and memories (legacy) tables."""
    items: list[dict[str, object]] = []
    try:
        db = _get_db()
        from cogito_agent.storage.repositories import MemoryItemRepository, MemoryRepository
        v2_repo = MemoryItemRepository(db)
        old_repo = MemoryRepository(db)

        # Memory v2 items
        for row in v2_repo.list_active_with_filters(workspace_id, memory_type=type_, q=q):
            d = dict(row)
            d["id"] = str(d["id"])
            d["section"] = d.get("type", "general")
            d["status"] = "active"
            d["confidence"] = min(1.0, float(d.get("reinforcement", 1) or 1) * 0.1)
            d["summary"] = ""
            items.append(d)

        # Legacy memories table
        for row in old_repo.list_active_or_archived(
            workspace_id, memory_type=type_, q=q, archived_filter=archived_filter,
        ):
            d = dict(row)
            d["id"] = str(d["id"])
            d["section"] = d.get("type", "general")
            d["status"] = "archived" if d.get("archived_at") else "active"
            d["summary"] = ""
            items.append(d)
    except Exception:
        pass
    return items


def _get_one(id: str, workspace_id: str) -> dict[str, object] | None:
    """Look up a memory by id from memory_items or memories table."""
    try:
        db = _get_db()
        from cogito_agent.storage.repositories import MemoryItemRepository, MemoryRepository
        item = MemoryItemRepository(db).get_by_id(id, workspace_id)
        if item:
            d = dict(item)
            d["section"] = d.get("memory_type", "general")
            d["status"] = "active"
            return d
        item = MemoryRepository(db).get_by_id(id, workspace_id)
        if item:
            d = dict(item)
            d["section"] = d.get("type", "general")
            d["status"] = "archived" if d.get("archived_at") else "active"
            return d
    except Exception:
        pass
    return None


# ─── Redaction ────────────────────────────────────────────────────────


def _redact_item(item: dict[str, object]) -> dict[str, object]:
    return {k: redact_html(v) if isinstance(v, str) else v for k, v in item.items()}


def _audit_log(actor: str, action: str, resource: str, workspace_id: str,
               details: dict[str, object] | None = None) -> None:
    from cogito_agent.application.audit import log_audit
    log_audit(
        _get_db(), actor, action, resource, workspace_id,
        details=json.dumps(details or {}, default=str),
    )


# ─── Routes ───────────────────────────────────────────────────────────


@memory_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def memory_page(
    request: Request,
    tab: str = Query("all"),
    status: str = Query(""),
    type: str = Query(""),
    q: str = Query(""),
) -> HTMLResponse:
    stats = _mem_stats(CONSOLE_WORKSPACE_ID)
    items = _list_all(CONSOLE_WORKSPACE_ID, type, q)
    if tab == "all":
        items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    ctx: dict[str, object] = {
        "request": request, "title": "Memory", "version": APP_VERSION,
        "stats": stats, "tab": tab, "status": status, "type": type, "q": q,
        "items": [_redact_item(i) for i in items],
        "is_candidate": {},
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/memory.html", ctx)


@memory_router.get("/{id}", response_class=HTMLResponse, include_in_schema=False)
async def memory_detail(request: Request, id: str) -> HTMLResponse:
    item = _get_one(id, CONSOLE_WORKSPACE_ID)
    if item is None:
        return templates.TemplateResponse(
            request, "console/error.html",
            {"request": request, "title": "Not Found",
             "message": f"Memory '{id}' not found.", "menu": _menu_items()},
            status_code=404,
        )
    ctx = {
        "request": request, "title": "Memory Detail", "version": APP_VERSION,
        "item": _redact_item(item), "item_type": "memory", "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/memory_detail.html", ctx)


@memory_router.post("/{memory_id}/edit", response_class=HTMLResponse, include_in_schema=False)
async def memory_edit(request: Request, memory_id: str, text: str = Form(...)) -> HTMLResponse:
    rid = str(uuid.uuid4())
    try:
        from cogito_agent.governance import AuditLogger
        from cogito_agent.memory.application import MemoryApplicationService
        svc = MemoryApplicationService(_get_db())
        ok = svc.edit_memory(memory_id, CONSOLE_WORKSPACE_ID, text, actor_id=CONSOLE_ACTOR)
        if not ok:
            return _error_partial(request, "Memory not found", rid)
        _audit_log(CONSOLE_ACTOR, "memory.edit", f"memory:{memory_id}", CONSOLE_WORKSPACE_ID)
        return templates.TemplateResponse(
            request, "console/components/memory_success.html",
            {"request": request, "message": "Memory updated.", "menu": _menu_items()},
        )
    except Exception as e:
        return _error_partial(request, f"Failed: {e}", rid)


@memory_router.post("/{memory_id}/archive", response_class=HTMLResponse, include_in_schema=False)
async def memory_archive(request: Request, memory_id: str) -> HTMLResponse:
    rid = str(uuid.uuid4())
    try:
        from cogito_agent.governance import AuditLogger
        from cogito_agent.memory.application import MemoryApplicationService
        svc = MemoryApplicationService(_get_db())
        ok = svc.archive_memory(memory_id, CONSOLE_WORKSPACE_ID, actor_id=CONSOLE_ACTOR)
        if not ok:
            return _error_partial(request, "Memory not found", rid)
        _audit_log(CONSOLE_ACTOR, "memory.archive", f"memory:{memory_id}", CONSOLE_WORKSPACE_ID)
        return templates.TemplateResponse(
            request, "console/components/memory_success.html",
            {"request": request, "message": "Memory archived.", "menu": _menu_items()},
        )
    except Exception as e:
        return _error_partial(request, f"Failed: {e}", rid)


@memory_router.post("/{memory_id}/delete", response_class=HTMLResponse, include_in_schema=False)
async def memory_delete(request: Request, memory_id: str) -> HTMLResponse:
    rid = str(uuid.uuid4())
    try:
        from cogito_agent.governance import AuditLogger
        from cogito_agent.memory.application import MemoryApplicationService
        svc = MemoryApplicationService(_get_db())
        ok = svc.soft_delete_memory(memory_id, CONSOLE_WORKSPACE_ID, actor_id=CONSOLE_ACTOR)
        if not ok:
            return _error_partial(request, "Memory not found", rid)
        _audit_log(CONSOLE_ACTOR, "memory.delete", f"memory:{memory_id}", CONSOLE_WORKSPACE_ID)
        return templates.TemplateResponse(
            request, "console/components/memory_success.html",
            {"request": request, "message": "Memory deleted.", "menu": _menu_items()},
        )
    except Exception as e:
        return _error_partial(request, f"Failed: {e}", rid)


# ─── Error partial ────────────────────────────────────────────────────


def _error_partial(request: Request, message: str, request_id: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "console/components/error_banner.html",
        {"request": request, "error": redact_html(message),
         "request_id": request_id, "menu": _menu_items()},
        status_code=404,
    )
