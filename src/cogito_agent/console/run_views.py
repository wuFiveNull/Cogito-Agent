from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from cogito_agent.application import RunApplicationService
from cogito_agent.governance import AuditLogger
from cogito_agent.runs import RunRepository
from cogito_agent.shared import SkillManifest
from cogito_agent.skill import SkillPool, SkillRunner
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
run_router = APIRouter()
WORKSPACE_ID = "default"


def _service() -> RunApplicationService:
    from cogito_agent.storage import get_db

    db = get_db()

    def dispatch_retry(run: dict[str, object]) -> None:
        if run.get("run_type") != "skill":
            return
        pool_entry = SkillPool(db).get(str(run.get("definition_id", "")))
        if pool_entry is None:
            raise RuntimeError("Installed skill manifest not found")
        manifest = SkillManifest(**json.loads(str(pool_entry["manifest_json"])))
        input_data = json.loads(str(run.get("input_json", "{}")))
        raw_inputs = input_data.get("inputs", {})
        inputs = (
            {str(key): str(value) for key, value in raw_inputs.items()}
            if isinstance(raw_inputs, dict)
            else {}
        )
        SkillRunner(db).run(
            manifest,
            str(run.get("workspace_id", WORKSPACE_ID)),
            str(input_data.get("session_id", "")),
            inputs,
            durable_run_id=str(run["id"]),
        )

    return RunApplicationService(
        RunRepository(db),
        AuditLogger(db),
        retry_dispatcher=dispatch_retry,
    )


def _safe(item: dict[str, object]) -> dict[str, object]:
    return {
        key: redact_html(value) if isinstance(value, str) else value for key, value in item.items()
    }


@run_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def run_list(
    request: Request,
    status: str = "",
    run_type: str = "",
) -> HTMLResponse:
    runs = [
        _safe(item)
        for item in _service().list_runs(
            workspace_id=WORKSPACE_ID,
            status=status or None,
            run_type=run_type or None,
        )
    ]
    context: dict[str, object] = {
        "request": request,
        "title": "Runs",
        "version": APP_VERSION,
        "menu": menu_items(),
        "runs": runs,
        "status_filter": status,
        "type_filter": run_type,
    }
    return templates.TemplateResponse(request, "console/runs.html", context)


@run_router.get("/{run_id}", response_class=HTMLResponse, include_in_schema=False)
async def run_detail(request: Request, run_id: str) -> HTMLResponse:
    run = _service().get_run(run_id)
    if run is None:
        context: dict[str, object] = {
            "request": request,
            "title": "Run Not Found",
            "version": APP_VERSION,
            "menu": menu_items(),
            "message": "Run not found.",
        }
        return templates.TemplateResponse(
            request,
            "console/error.html",
            context,
            status_code=404,
        )
    events = run.get("events", [])
    outputs = run.get("outputs", [])
    event_items = events if isinstance(events, list) else []
    output_items = outputs if isinstance(outputs, list) else []
    run["events"] = [_safe(dict(item)) for item in event_items if isinstance(item, dict)]
    run["outputs"] = [_safe(dict(item)) for item in output_items if isinstance(item, dict)]
    context = {
        "request": request,
        "title": f"Run: {run.get('definition_id') or run.get('run_type')}",
        "version": APP_VERSION,
        "menu": menu_items(),
        "run": _safe(run),
    }
    return templates.TemplateResponse(request, "console/run_detail.html", context)


@run_router.post("/{run_id}/cancel", include_in_schema=False)
async def run_cancel(
    request: Request,
    run_id: str,
    reason: str = Form("cancelled from console"),
) -> Response:
    _service().cancel(run_id, workspace_id=WORKSPACE_ID, reason=reason)
    return RedirectResponse(f"/console/runs/{run_id}", status_code=303)


@run_router.post("/{run_id}/retry", include_in_schema=False)
async def run_retry(request: Request, run_id: str) -> Response:
    _service().retry(run_id, workspace_id=WORKSPACE_ID)
    return RedirectResponse(f"/console/runs/{run_id}", status_code=303)
