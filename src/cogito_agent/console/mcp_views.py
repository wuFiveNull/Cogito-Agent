from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from cogito_agent.application import MCPApplicationService
from cogito_agent.governance import AuditLogger
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
mcp_router = APIRouter()
WORKSPACE_ID = "default"


def _service() -> MCPApplicationService:
    from cogito_agent.api.app import get_db, get_mcp_manager
    from cogito_agent.storage.mcp_calls import SqliteMCPCallReader

    db = get_db()
    return MCPApplicationService(
        get_mcp_manager(),
        AuditLogger(db),
        SqliteMCPCallReader(db),
    )


def _present_servers() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw_server in _service().list_servers():
        server = dict(raw_server)
        server["name"] = redact_html(str(server.get("name", "")))
        grants: list[dict[str, object]] = []
        for raw_grant in server.get("tool_grants", []):
            if not isinstance(raw_grant, dict):
                continue
            grant = dict(raw_grant)
            for key in ("tool_name", "schema_hash", "risk_level"):
                grant[key] = redact_html(str(grant.get(key, "")))
            try:
                sources = json.loads(str(grant.get("allowed_sources_json", "[]")))
            except (TypeError, ValueError):
                sources = []
            grant["allowed_sources"] = ", ".join(str(item) for item in sources)
            grant["active"] = bool(grant.get("granted_at")) and not bool(grant.get("revoked_at"))
            grants.append(grant)
        server["tool_grants"] = grants
        server["recent_calls"] = [
            {
                key: redact_html(str(value)) if isinstance(value, str) else value
                for key, value in call.items()
            }
            for call in _service().list_recent_calls(str(raw_server.get("name", "")))
        ]
        result.append(server)
    return result


@mcp_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def mcp_page(request: Request) -> HTMLResponse:
    context: dict[str, object] = {
        "request": request,
        "title": "MCP Trust & Grants",
        "version": APP_VERSION,
        "menu": menu_items(),
        "servers": _present_servers(),
    }
    return templates.TemplateResponse(request, "console/mcp.html", context)


@mcp_router.post("/sync", include_in_schema=False)
async def mcp_sync(request: Request) -> Response:
    _service().sync()
    return RedirectResponse("/console/mcp", status_code=303)


@mcp_router.post("/{name}/trust", include_in_schema=False)
async def mcp_trust(request: Request, name: str) -> Response:
    _service().trust(name, workspace_id=WORKSPACE_ID)
    return RedirectResponse("/console/mcp", status_code=303)


@mcp_router.post("/{name}/block", include_in_schema=False)
async def mcp_block(request: Request, name: str) -> Response:
    _service().block(name, workspace_id=WORKSPACE_ID)
    return RedirectResponse("/console/mcp", status_code=303)


@mcp_router.post("/{name}/tools/{tool_name}/grant", include_in_schema=False)
async def mcp_grant(
    request: Request,
    name: str,
    tool_name: str,
    schema_hash: str = Form(...),
    allowed_sources: str = Form("interactive"),
    requires_approval: bool = Form(False),
) -> Response:
    sources = [item.strip() for item in allowed_sources.split(",") if item.strip()]
    _service().grant(
        name,
        tool_name,
        schema_hash=schema_hash,
        allowed_sources=sources,
        requires_approval=requires_approval,
        workspace_id=WORKSPACE_ID,
    )
    return RedirectResponse("/console/mcp", status_code=303)


@mcp_router.post("/{name}/tools/{tool_name}/revoke", include_in_schema=False)
async def mcp_revoke(request: Request, name: str, tool_name: str) -> Response:
    _service().revoke(name, tool_name, workspace_id=WORKSPACE_ID)
    return RedirectResponse("/console/mcp", status_code=303)
