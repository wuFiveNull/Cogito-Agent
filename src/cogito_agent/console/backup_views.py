from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.application import BackupApplicationService
from cogito_agent.application.audit import log_audit
from cogito_agent.config import Settings
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
backup_router = APIRouter()
WORKSPACE_ID = "default"


def _service() -> BackupApplicationService:
    from cogito_agent.api.app import reset_application_state_for_restore
    from cogito_agent.storage import get_db

    db = get_db()
    settings = Settings.get().storage

    def audit_restored(name: str, workspace_id: str) -> None:
        log_audit(
            get_db(), "console", "backup.restore.completed", name, workspace_id,
            reason="restore completed",
        )

    return BackupApplicationService(
        db_path=db.path,
        backup_dir=settings.backup_dir,
        reset_before_restore=reset_application_state_for_restore,
        restore_completed=audit_restored,
    )


def _context(
    request: Request,
    service: BackupApplicationService,
    *,
    report: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, object]:
    return {
        "request": request,
        "title": "Backup & Restore",
        "version": APP_VERSION,
        "menu": menu_items(),
        "available": service.available,
        "backups": service.list_backups(),
        "report": report,
        "error": redact_html(error),
    }


@backup_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def backup_page(request: Request) -> HTMLResponse:
    service = _service()
    return templates.TemplateResponse(
        request,
        "console/backups.html",
        _context(request, service),
    )


@backup_router.post("/create", response_class=HTMLResponse, include_in_schema=False)
async def backup_create(request: Request) -> HTMLResponse:
    service = _service()
    try:
        report = service.create(workspace_id=WORKSPACE_ID)
        context = _context(request, service, report=report)
    except Exception as exc:
        context = _context(request, service, error=str(exc))
    return templates.TemplateResponse(request, "console/backups.html", context)


@backup_router.post("/preflight", response_class=HTMLResponse, include_in_schema=False)
async def backup_preflight(request: Request, name: str = Form(...)) -> HTMLResponse:
    service = _service()
    try:
        context = _context(request, service, report=service.preflight(name))
        context["selected_backup"] = redact_html(name)
    except Exception as exc:
        context = _context(request, service, error=str(exc))
    return templates.TemplateResponse(request, "console/backups.html", context)


@backup_router.post("/restore", response_class=HTMLResponse, include_in_schema=False)
async def backup_restore(
    request: Request,
    name: str = Form(...),
    confirmation: str = Form(...),
) -> HTMLResponse:
    service = _service()
    try:
        report = service.restore(
            name,
            confirmation=confirmation,
            workspace_id=WORKSPACE_ID,
        )
        context = _context(request, service, report=report)
    except Exception as exc:
        context = _context(request, service, error=str(exc))
    return templates.TemplateResponse(request, "console/backups.html", context)
