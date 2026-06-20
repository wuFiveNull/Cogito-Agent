from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database as _Database
from cogito_agent.version import APP_VERSION

from .redaction import redact_html
from .utils import menu_items as _menu_items

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

trace_router = APIRouter()

CONSOLE_WORKSPACE_ID = "default"


# ─── helpers ─────────────────────────────────────────────────────────────────


def _get_db() -> _Database:
    from cogito_agent.api.app import get_db as _get_shared_db

    return _get_shared_db()


def _duration_ms(start: str, end: str | None) -> int | None:
    if not end:
        return None
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        s = datetime.strptime(str(start)[:19], fmt)
        e = datetime.strptime(str(end)[:19], fmt)
        return int((e - s).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


def _time_filter(days: int | None = None) -> str:
    if days is None:
        return ""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    return cutoff


def _list_traces(
    workspace_id: str,
    status: str = "",
    kind: str = "",
    q: str = "",
    time_range: str = "",
    limit: int = 100,
) -> list[dict[str, object]]:
    db = _get_db()
    params: list[Any] = []

    where_clauses: list[str] = []
    if workspace_id and workspace_id != "*":
        where_clauses.append("t.workspace_id=?")
        params.append(workspace_id)

    if status and status != "all":
        where_clauses.append("t.status=?")
        params.append(status)

    if q:
        where_clauses.append("(t.id LIKE ? OR t.root_event_id LIKE ?)")
        like = f"%{q}%"
        params.append(like)
        params.append(like)

    if time_range:
        days_map = {"1h": 1 / 24, "24h": 1, "7d": 7}
        days = days_map.get(time_range, 0)
        if days:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            where_clauses.append("t.started_at >= ?")
            params.append(cutoff)

    where = ""
    if where_clauses:
        where = "WHERE " + " AND ".join(where_clauses)

    sql = (
        "SELECT t.*,"
        " (SELECT COUNT(*) FROM spans s WHERE s.trace_id = t.id) AS span_count"
        " FROM traces t"
        f" {where}"
        " ORDER BY t.started_at DESC LIMIT ?"
    )
    params.append(limit)
    rows = db.connection.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _trace_stats(workspace_id: str) -> dict[str, int]:
    db = _get_db()
    cur = db.connection
    wc = "WHERE workspace_id=?" if workspace_id != "*" else ""
    params = (workspace_id,) if workspace_id != "*" else ()
    total = cur.execute(f"SELECT COUNT(*) FROM traces {wc}", params).fetchone()[0]
    ok = cur.execute(
        f"SELECT COUNT(*) FROM traces {wc} AND status='completed'" if wc
        else "SELECT COUNT(*) FROM traces WHERE status='completed'",
        params if wc else (),
    ).fetchone()[0]
    err = cur.execute(
        f"SELECT COUNT(*) FROM traces {wc} AND status='error'" if wc
        else "SELECT COUNT(*) FROM traces WHERE status='error'",
        params if wc else (),
    ).fetchone()[0]
    return {"total": total, "completed": ok, "error": err}


def _build_span_tree(
    spans: list[dict[str, object]],
) -> list[dict[str, object]]:
    children_map: dict[str, list[dict[str, object]]] = {}
    roots: list[dict[str, object]] = []
    for s in spans:
        pid = str(s.get("parent_span_id") or "")
        if pid:
            children_map.setdefault(pid, []).append(s)
        else:
            roots.append(s)

    def _attach_children(node: dict[str, object]) -> dict[str, object]:
        sid = str(node.get("id", ""))
        node["children"] = [
            _attach_children(c) for c in children_map.get(sid, [])
        ]
        return node

    return [_attach_children(r) for r in roots]


def _redact_item(item: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for k, v in item.items():
        if isinstance(v, str):
            result[k] = redact_html(v)
        else:
            result[k] = v
    return result


# ─── List page ────────────────────────────────────────────────────────────────


@trace_router.get("", response_class=HTMLResponse, include_in_schema=False)
async def traces_page(
    request: Request,
    status: str = Query(""),
    kind: str = Query(""),
    q: str = Query(""),
    time_range: str = Query("24h"),
) -> HTMLResponse:
    stats = _trace_stats(CONSOLE_WORKSPACE_ID)
    items = _list_traces(CONSOLE_WORKSPACE_ID, status, kind, q, time_range)
    items = [_redact_item(i) for i in items]

    for item in items:
        item["_duration_ms"] = _duration_ms(
            str(item.get("started_at", "")),
            str(item.get("ended_at") or ""),
        )

    ctx: dict[str, object] = {
        "request": request,
        "title": "Traces",
        "version": APP_VERSION,
        "stats": stats,
        "status": status,
        "kind": kind,
        "q": q,
        "time_range": time_range,
        "items": items,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/traces.html", ctx)


# ─── Detail page ──────────────────────────────────────────────────────────────


@trace_router.get("/{trace_id}", response_class=HTMLResponse, include_in_schema=False)
async def trace_detail(request: Request, trace_id: str) -> HTMLResponse:
    from cogito_agent.cli.replay import TraceInspector

    db = _get_db()
    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(trace_id)
    if trace is None:
        error_ctx: dict[str, object] = {
            "request": request,
            "title": "Not Found",
            "message": f"Trace '{trace_id}' not found.",
            "menu": _menu_items(),
        }
        return templates.TemplateResponse(request, "console/error.html", error_ctx, status_code=404)

    trace = _redact_item(trace)
    raw_spans: list[dict[str, object]] = cast(
        list[dict[str, object]], trace.get("spans") or [],
    )
    tree = _build_span_tree(raw_spans)

    for s in raw_spans:
        s["_duration_ms"] = _duration_ms(
            str(s.get("started_at", "")),
            str(s.get("ended_at") or ""),
        )

    raw_mc: list[dict[str, object]] = cast(
        list[dict[str, object]], trace.get("model_calls") or [],
    )
    model_calls = [_redact_item(m) for m in raw_mc]

    raw_tc: list[dict[str, object]] = cast(
        list[dict[str, object]], trace.get("tool_calls") or [],
    )
    tool_calls = [_redact_item(t) for t in raw_tc]

    raw_al: list[dict[str, object]] = cast(
        list[dict[str, object]], trace.get("audit_logs") or [],
    )
    audit_logs = [_redact_item(a) for a in raw_al]

    raw_json = json.dumps(trace, indent=2, default=str)
    raw_json = redact_html(raw_json)

    ctx: dict[str, object] = {
        "request": request,
        "title": "Trace Detail",
        "version": APP_VERSION,
        "trace": trace,
        "tree": tree,
        "spans": raw_spans,
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "audit_logs": audit_logs,
        "raw_json": raw_json,
        "menu": _menu_items(),
    }
    return templates.TemplateResponse(request, "console/trace_detail.html", ctx)
