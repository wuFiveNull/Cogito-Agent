from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

workspace_files_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"


def _get_db() -> _Database:
    from cogito_agent.storage import get_db as _get_shared_db

    return _get_shared_db()


def _ensure_workspace(workspace_id: str) -> None:
    from cogito_agent.application import WorkspaceApplicationService

    WorkspaceApplicationService(_get_db()).ensure_workspace(workspace_id)


def _redact_item(item: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in item.items():
        if isinstance(v, str):
            result[k] = redact_html(v)
        else:
            result[k] = v
    return result


def _ensure_root(workspace_id: str) -> str:
    from cogito_agent.workspace import WorkspaceFileRegistry

    db = _get_db()
    reg = WorkspaceFileRegistry(db)
    roots = reg.list_roots(workspace_id)
    if not roots:
        root_path = Path.cwd() / "workspace"
        root_path.mkdir(parents=True, exist_ok=True)
        root = reg.register_root(
            workspace_id=workspace_id,
            root_path=str(root_path),
            label="Default workspace root",
            ignore_patterns="*.log\n.DS_Store\n.git\n__pycache__\n*.pyc\n.env\nnode_modules",
        )
        return str(root["id"])
    return str(roots[0]["id"])


@workspace_files_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def workspace_files_list(
    request: Request,
    root_id: str = Query(""),
    status: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.workspace import WorkspaceFileRegistry

    reg = WorkspaceFileRegistry(db)
    roots = reg.list_roots(CONSOLE_WORKSPACE_ID)
    cur_root_id = root_id or (_ensure_root(CONSOLE_WORKSPACE_ID) if roots else "")
    files = reg.list_files(CONSOLE_WORKSPACE_ID, root_id=cur_root_id, status=status)
    counts: dict[str, int] = {"active": 0, "deleted": 0, "ignored": 0, "error": 0}
    for f in files:
        s = str(f.get("status", "active"))
        counts[s] = counts.get(s, 0) + 1
    ctx: dict[str, object] = {
        "request": request,
        "title": "Workspace Files",
        "version": APP_VERSION,
        "menu": _menu_items(),
        "roots": roots,
        "cur_root_id": cur_root_id,
        "files": files,
        "counts": counts,
        "status_filter": status,
    }
    return templates.TemplateResponse(request, "console/workspace_files.html", ctx)


@workspace_files_router.get("/{fid}", response_class=HTMLResponse, include_in_schema=False)
async def workspace_file_detail(request: Request, fid: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.workspace import FileIngestionService, WorkspaceFileRegistry

    reg = WorkspaceFileRegistry(db)
    ing = FileIngestionService(db)
    row = reg.get_file_by_id(fid, CONSOLE_WORKSPACE_ID)
    if row is None:
        ctx: dict[str, object] = {
            "request": request,
            "title": "File Not Found",
            "message": "File not found in workspace index.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)
    chunks = ing.get_file_chunks(fid, CONSOLE_WORKSPACE_ID)
    item = _redact_item(dict(row))
    detail_ctx: dict[str, object] = {
        "request": request,
        "title": f"File: {item.get('file_name', 'Unknown')}",
        "version": APP_VERSION,
        "menu": _menu_items(),
        "file": item,
        "chunks": [_redact_item(c) for c in chunks],
    }
    return templates.TemplateResponse(request, "console/workspace_file_detail.html", detail_ctx)


@workspace_files_router.post("/scan", include_in_schema=False)
async def workspace_files_scan(
    request: Request,
    root_id: str = Form(""),
) -> RedirectResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.workspace import FileIngestionService, WorkspaceFileRegistry

    reg = WorkspaceFileRegistry(db)
    if not root_id:
        roots = reg.list_roots(CONSOLE_WORKSPACE_ID)
        if not roots:
            return RedirectResponse(url="/console/workspace/files", status_code=303)
        root_id = str(roots[0]["id"])
    ing = FileIngestionService(db)
    ing.scan_root(root_id, CONSOLE_WORKSPACE_ID)
    return RedirectResponse(url="/console/workspace/files", status_code=303)


@workspace_files_router.post("/{fid}/reindex", include_in_schema=False)
async def workspace_file_reindex(request: Request, fid: str) -> RedirectResponse:
    db = _get_db()
    from cogito_agent.workspace import FileIngestionService

    ing = FileIngestionService(db)
    ing.reindex_file(fid, CONSOLE_WORKSPACE_ID)
    return RedirectResponse(url=f"/console/workspace/files/{fid}", status_code=303)


@workspace_files_router.post("/{fid}/remove", include_in_schema=False)
async def workspace_file_remove(request: Request, fid: str) -> RedirectResponse:
    db = _get_db()
    from cogito_agent.workspace import WorkspaceFileRegistry

    reg = WorkspaceFileRegistry(db)
    reg.remove_file(fid, CONSOLE_WORKSPACE_ID)
    return RedirectResponse(url="/console/workspace/files", status_code=303)
