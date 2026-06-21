from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

artifact_router = APIRouter()

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


@artifact_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def artifacts_list(
    request: Request,
    source_type: str = Query(""),
    artifact_type: str = Query(""),
) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.workspace import ArtifactService

    svc = ArtifactService(db)
    artifacts = svc.list_artifacts(
        CONSOLE_WORKSPACE_ID,
        source_type=source_type,
        artifact_type=artifact_type,
    )
    redacted = [_redact_item(a) for a in artifacts]
    ctx: dict[str, object] = {
        "request": request,
        "title": "Artifacts",
        "version": APP_VERSION,
        "menu": _menu_items(),
        "artifacts": redacted,
        "source_type_filter": source_type,
        "artifact_type_filter": artifact_type,
    }
    return templates.TemplateResponse(request, "console/artifacts.html", ctx)


@artifact_router.get("/{aid}", response_class=HTMLResponse, include_in_schema=False)
async def artifact_detail(request: Request, aid: str) -> HTMLResponse:
    _ensure_workspace(CONSOLE_WORKSPACE_ID)
    db = _get_db()
    from cogito_agent.workspace import ArtifactService

    svc = ArtifactService(db)
    row = svc.get_artifact_by_id(aid, CONSOLE_WORKSPACE_ID)
    if row is None:
        ctx: dict[str, object] = {
            "request": request,
            "title": "Artifact Not Found",
            "message": "Artifact not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", ctx, status_code=404)
    html_content = svc.render_artifact_html(aid)
    item = _redact_item(dict(row))
    detail_ctx: dict[str, object] = {
        "request": request,
        "title": f"Artifact: {item.get('title', 'Unknown')}",
        "version": APP_VERSION,
        "menu": _menu_items(),
        "artifact": item,
        "html_content": html_content,
    }
    return templates.TemplateResponse(request, "console/artifact_detail.html", detail_ctx)


@artifact_router.get("/{aid}/download", include_in_schema=False)
async def artifact_download(request: Request, aid: str) -> Response:
    db = _get_db()
    from cogito_agent.workspace import ArtifactService

    svc = ArtifactService(db)
    row = svc.get_artifact_by_id(aid, CONSOLE_WORKSPACE_ID)
    if row is None:
        return Response(status_code=404)
    content = svc.get_artifact_content(aid)
    mime = str(row.get("mime_type", "text/plain"))
    fname = Path(str(row.get("title", "artifact"))).name
    fname = fname.replace('"', "_").replace("\r", "_").replace("\n", "_")
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@artifact_router.post("/{aid}/delete", include_in_schema=False)
async def artifact_delete(request: Request, aid: str) -> RedirectResponse:
    db = _get_db()
    from cogito_agent.workspace import ArtifactService

    svc = ArtifactService(db)
    svc.delete_artifact(aid, CONSOLE_WORKSPACE_ID)
    return RedirectResponse(url="/console/artifacts", status_code=303)
