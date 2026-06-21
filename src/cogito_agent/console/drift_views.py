from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

drift_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"


def _get_db() -> _Database:
    from cogito_agent.api.app import get_db as _get_shared_db

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


@drift_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def drift_dashboard(request: Request) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.runtime import DriftRuntime

    drift = DriftRuntime(db)
    drift._ensure_state()

    status = drift.status()
    runs = drift.list_runs(CONSOLE_WORKSPACE_ID, 50)

    for r in runs:
        r["artifact_id"] = redact_html(str(r.get("artifact_id", "")))
        r["error_message"] = redact_html(str(r.get("error_message", "")))

    ctx: dict[str, object] = {
        "request": request,
        "title": "Drift Runtime",
        "version": APP_VERSION,
        "menu": _menu_items(),
        "status": status,
        "runs": runs,
    }
    return templates.TemplateResponse(request, "console/drift.html", ctx)


@drift_router.post("/pause", include_in_schema=False)
async def drift_pause(request: Request, reason: str = Form("")) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.application import DriftApplicationService
    from cogito_agent.runtime import DriftRuntime

    DriftApplicationService(DriftRuntime(db)).pause(reason)
    return RedirectResponse(url="/console/drift", status_code=303)


@drift_router.post("/resume", include_in_schema=False)
async def drift_resume(request: Request) -> Response:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.application import DriftApplicationService
    from cogito_agent.runtime import DriftRuntime

    DriftApplicationService(DriftRuntime(db)).resume()
    return RedirectResponse(url="/console/drift", status_code=303)


@drift_router.get("/runs/{run_id}", response_class=HTMLResponse, include_in_schema=False)
async def drift_run_detail(request: Request, run_id: str) -> HTMLResponse:
    db = _get_db()
    from cogito_agent.runtime import DriftRuntime

    drift = DriftRuntime(db)
    run = drift.get_run(run_id)
    if run is None:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Drift Run Not Found",
            "message": "Drift run not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)

    item = _redact_item(dict(run))
    detail_ctx: dict[str, object] = {
        "request": request,
        "title": f"Drift Run: {run.get('skill_name', 'Unknown')}",
        "version": APP_VERSION,
        "menu": _menu_items(),
        "run": item,
    }
    return templates.TemplateResponse(request, "console/drift_run_detail.html", detail_ctx)
