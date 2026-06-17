# mypy: disable-error-code="return-value"
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from cogito_agent.cli.export import _redact_dict
from cogito_agent.console import console_router, status_router
from cogito_agent.mcp import MCPServerConfig, MCPServerManager
from cogito_agent.models import list_providers
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, SkillManifest, StreamEventType
from cogito_agent.skill import SkillPool, SkillRunner, WorkspaceSkill
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    ApprovalRepository,
    MemoryCandidateRepository,
    MemoryEditRepository,
    SessionRepository,
    WorkspaceRepository,
    WorkspaceSettingsRepository,
)
from cogito_agent.trace.redaction import RedactionHelper

logger = logging.getLogger(__name__)

_RATE_LIMITER: dict[str, list[float]] = {}


def _error_response(
    code: str,
    message: str,
    request_id: str,
    trace_id: str | None = None,
    retryable: bool = False,
    status_code: int = 400,
) -> JSONResponse:
    safe_message = RedactionHelper().redact(message)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": safe_message,
                "request_id": request_id,
                "trace_id": trace_id,
                "retryable": retryable,
            }
        },
    )


def _check_rate_limit(request: Request) -> bool:
    enabled = os.environ.get("COGITO_RATE_LIMIT_ENABLED", "0") == "1"
    if not enabled:
        return True
    per_minute = int(os.environ.get("COGITO_RATE_LIMIT_PER_MINUTE", "60"))
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = 60.0
    if client_ip not in _RATE_LIMITER:
        _RATE_LIMITER[client_ip] = []
    _RATE_LIMITER[client_ip] = [t for t in _RATE_LIMITER[client_ip] if now - t < window]
    if len(_RATE_LIMITER[client_ip]) >= per_minute:
        return False
    _RATE_LIMITER[client_ip].append(now)
    return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not _check_rate_limit(request):
            return _error_response(
                "RATE_LIMITED", "Rate limit exceeded", request.state.request_id,
                retryable=True, status_code=429,
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_db()
    get_kernel()
    yield


app = FastAPI(title="Cogito-Agent API", version="0.8.0-dev", lifespan=lifespan)

_console_static = Path(__file__).resolve().parent.parent / "console" / "static"
app.mount("/console/static", StaticFiles(directory=str(_console_static)), name="console_static")
app.include_router(console_router, prefix="/console")
app.include_router(status_router, prefix="/api/v1/status")


@app.get("/api/v1/doctor", include_in_schema=False)
async def doctor_api_endpoint(live: str = Query("")) -> JSONResponse:
    if live and live not in ("", "0", "false"):
        return JSONResponse(
            status_code=501,
            content={
                "status": "error",
                "version": os.environ.get("COGITO_CONSOLE_VERSION", "0.8.0-dev"),
                "checks": [{
                    "section": "provider",
                    "name": "live_check",
                    "status": "skipped",
                    "message": "Live provider check not implemented in console viewer",
                }],
                "limitations": ["Live provider check not available in console viewer"],
            },
        )
    from cogito_agent.console.doctor_views import _build_checks, _overall_status
    checks = _build_checks()
    overall = _overall_status(checks)
    return JSONResponse({
        "status": overall,
        "version": os.environ.get("COGITO_CONSOLE_VERSION", "0.8.0-dev"),
        "checks": checks,
        "limitations": [
            "No real Telegram/Feishu delivery for outbox",
            "Live provider check not run by default",
            "Config viewer is read-only in v0.8 Phase 7",
        ],
    })


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return _error_response(
        "VALIDATION_ERROR", str(exc.errors()), rid, status_code=422,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    rid = getattr(request.state, "request_id", "")
    return _error_response(
        "INTERNAL_ERROR", "Internal server error", rid, status_code=500,
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        api_key = os.environ.get("COGITO_API_KEY", "")
        if not api_key:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == api_key:
            return await call_next(request)
        rid = getattr(request.state, "request_id", "")
        return _error_response("UNAUTHORIZED", "Unauthorized", rid, status_code=401)


# Order: innermost first, outermost last.
# RequestIDMiddleware must run first (outermost) so request.state.request_id is set
# before AuthMiddleware/RateLimitMiddleware dispatch.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIDMiddleware)


_db: Database | None = None
_kernel: RuntimeKernel | None = None
_mcp_manager: MCPServerManager | None = None


def get_mcp_manager() -> MCPServerManager:
    global _mcp_manager
    if _mcp_manager is None:
        from cogito_agent.capability import CapabilityRegistry

        _mcp_manager = MCPServerManager(CapabilityRegistry())
    return _mcp_manager


class ChatRequest(BaseModel):
    text: str
    session_id: str
    workspace_id: str


class ChatResponse(BaseModel):
    output: str
    error: str | None = None
    session_id: str
    state: str


class SessionCreate(BaseModel):
    workspace_id: str
    title: str = "API Session"


class ResumeRequest(BaseModel):
    approval_id: str
    session_id: str
    workspace_id: str
    decision: str = "approved"


class CandidateAction(BaseModel):
    candidate_id: str
    action: str


class MemoryUpdateRequest(BaseModel):
    text: str


class ApprovalResolveRequest(BaseModel):
    decision: str
    decided_by: str = "user"


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None
    max_daily_notifications: int | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
        _db.initialize()
        _db.migrate()
    return _db


def get_kernel() -> RuntimeKernel:
    global _kernel
    if _kernel is None:
        db = get_db()
        from cogito_agent.cli.config_manager import build_model_adapter_from_config
        adapter = build_model_adapter_from_config()
        _kernel = RuntimeKernel(db, model_adapter=adapter) if adapter else RuntimeKernel(db)
    return _kernel


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    db = get_db()
    kernel = get_kernel()
    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(req.session_id, req.workspace_id)
    if sess is None:
        return _error_response(
            "NOT_FOUND", "Session not found",
            request.state.request_id, status_code=404,
        )

    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": req.text, "_request_id": request.state.request_id},
    )
    result = kernel.process(event)
    return ChatResponse(
        output=result.output,
        error=result.error,
        session_id=req.session_id,
        state=result.state.value if hasattr(result.state, "value") else str(result.state),
    )


@app.post("/chat/resume", response_model=ChatResponse)
def resume_chat(req: ResumeRequest, request: Request) -> ChatResponse:
    db = get_db()
    kernel = get_kernel()
    repo = ApprovalRepository(db)
    approval = repo.resolve(req.approval_id, req.decision, "api")
    if approval is None:
        return _error_response(
            "NOT_FOUND", "Approval not found or already resolved",
            request.state.request_id, status_code=404,
        )
    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.resume,
        payload={"approval_id": req.approval_id, "_request_id": request.state.request_id},
    )
    result = kernel.resume(event) if hasattr(kernel, "resume") else kernel.process(event)
    return ChatResponse(
        output=result.output,
        error=result.error,
        session_id=req.session_id,
        state=result.state.value if hasattr(result.state, "value") else str(result.state),
    )


@app.post("/sessions")
def create_session(req: SessionCreate) -> dict[str, object]:
    db = get_db()
    ws_repo = WorkspaceRepository(db)
    ws = ws_repo.get_by_id(req.workspace_id)
    if ws is None:
        ws = ws_repo.create(req.workspace_id, req.workspace_id)
    sess_repo = SessionRepository(db)
    sid = str(uuid.uuid4())
    sess = sess_repo.create(sid, req.workspace_id, req.title)
    return dict(sess)


@app.get("/sessions")
def list_sessions(workspace_id: str) -> list[dict[str, object]]:
    db = get_db()
    sess_repo = SessionRepository(db)
    return sess_repo.list_by_workspace(workspace_id)


@app.get("/traces")
def list_traces(workspace_id: str) -> list[dict[str, object]]:
    from cogito_agent.cli.replay import TraceInspector

    inspector = TraceInspector(get_db())
    return inspector.list_traces(workspace_id)


@app.get("/traces/{trace_id}/full")
def get_trace_full(trace_id: str, request: Request) -> dict[str, object]:
    from cogito_agent.cli.replay import TraceInspector

    inspector = TraceInspector(get_db())
    trace = inspector.get_trace_full(trace_id)
    if trace is None:
        return _error_response(
            "NOT_FOUND", "Trace not found",
            request.state.request_id, status_code=404,
        )
    return trace


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str, request: Request) -> dict[str, object]:
    db = get_db()
    cur = db.connection.execute(
        "SELECT * FROM traces WHERE id = ?", (trace_id,)
    )
    row = cur.fetchone()
    if row is None:
        return _error_response(
            "NOT_FOUND", "Trace not found",
            request.state.request_id, status_code=404,
        )
    trace = dict(row)
    cur = db.connection.execute(
        "SELECT * FROM spans WHERE trace_id = ?", (trace_id,)
    )
    trace["spans"] = [dict(r) for r in cur.fetchall()]
    return trace


@app.post("/candidates")
def action_candidate(req: CandidateAction, request: Request) -> dict[str, object]:
    db = get_db()
    repo = MemoryCandidateRepository(db)
    if req.action == "accept":
        result = repo.accept(req.candidate_id)
    elif req.action == "reject":
        result = repo.reject(req.candidate_id)
    else:
        return _error_response(
            "VALIDATION_ERROR",
            "Invalid action, use 'accept' or 'reject'",
            request.state.request_id, status_code=400,
        )
    if result is None:
        return _error_response(
            "NOT_FOUND", "Candidate not found",
            request.state.request_id, status_code=404,
        )
    return result


class ChatStreamRequest(BaseModel):
    text: str
    session_id: str
    workspace_id: str


class SkillInstallRequest(BaseModel):
    manifest: SkillManifest


class WorkspaceSkillInstall(BaseModel):
    pool_skill_id: str


class RunSkillRequest(BaseModel):
    workspace_id: str
    inputs: dict[str, str] = {}


@app.post("/chat/stream")
def chat_stream(req: ChatStreamRequest, request: Request) -> StreamingResponse:
    db = get_db()
    kernel = get_kernel()
    redactor = RedactionHelper()
    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(req.session_id, req.workspace_id)
    if sess is None:
        return _error_response(
            "NOT_FOUND", "Session not found",
            request.state.request_id, status_code=404,
        )

    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={
            "text": req.text,
            "_request_id": request.state.request_id,
            "channel": "api_stream",
        },
    )

    def event_stream() -> Generator[str, None, None]:
        rid = request.state.request_id
        try:
            from cogito_agent.cli.config_manager import get_config
            cfg = get_config()
            streaming_enabled = cfg.get("model.streaming_enabled", "true").lower() == "true"
            max_retries = int(cfg.get("model.max_retries", "2"))
            for sev in kernel.process_stream(
                event, request_id=rid,
                streaming_enabled=streaming_enabled,
                max_retries=max_retries,
            ):
                if sev.type == StreamEventType.delta:
                    if "delta" in sev.data:
                        sev.data["delta"] = redactor.redact(str(sev.data["delta"]))
                    yield sev.to_sse()
                elif sev.type == StreamEventType.error:
                    raw_err = sev.data.get("error", {})
                    err_dict: dict[str, object] = dict(raw_err) if isinstance(raw_err, dict) else {}
                    err_dict["message"] = redactor.redact(str(err_dict.get("message", "")))
                    sev.data["error"] = err_dict
                    yield sev.to_sse()
                elif sev.type == StreamEventType.approval_required:
                    safe_summary = redactor.redact(str(sev.data.get("summary", "")))
                    sev.data["summary"] = safe_summary
                    yield sev.to_sse()
                else:
                    if "response" in sev.data:
                        sev.data["response"] = redactor.redact(str(sev.data["response"]))
                    yield sev.to_sse()
        except Exception:
            logger.exception("chat_stream runtime error")
            yield (
                f"event: error\n"
                f"data: {json.dumps({
                    'error': {
                        'code': 'RUNTIME_ERROR',
                        'message': 'Internal error during processing',
                        'request_id': rid,
                        'retryable': False,
                    },
                })}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        },
    )


@app.get("/providers")
def list_model_providers() -> dict[str, object]:
    return {"providers": list_providers()}


@app.get("/mcp/servers")
def list_mcp_servers() -> list[dict[str, object]]:
    return get_mcp_manager().list_servers()


@app.post("/mcp/servers")
def add_mcp_server(config: MCPServerConfig) -> dict[str, str]:
    get_mcp_manager().add_server(config)
    return {"status": "connected", "name": config.name}


@app.delete("/mcp/servers/{name}")
def remove_mcp_server(name: str) -> dict[str, str]:
    get_mcp_manager().remove_server(name)
    return {"status": "removed", "name": name}


@app.post("/mcp/sync")
def sync_mcp_servers() -> dict[str, object]:
    result = get_mcp_manager().sync()
    return {
        "status": "ok",
        "discovered": result["discovered"],
        "reconnected": result["reconnected"],
    }


@app.get("/mcp/discover")
def discover_mcp_configs(config_dir: str) -> list[dict[str, object]]:
    from cogito_agent.mcp import MCPServerConfig

    configs = MCPServerConfig.load_from_directory(config_dir)
    return [c.model_dump() for c in configs]


# --- Workspace management ---


@app.get("/workspaces")
def list_workspaces() -> list[dict[str, object]]:
    db = get_db()
    repo = WorkspaceRepository(db)
    return repo.list_all()


@app.post("/workspaces")
def create_workspace(name: str) -> dict[str, object]:
    db = get_db()
    repo = WorkspaceRepository(db)
    wid = str(uuid.uuid4())
    return repo.create(wid, name)


@app.get("/workspaces/{wid}")
def get_workspace(wid: str, request: Request) -> dict[str, object]:
    db = get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(wid)
    if ws is None:
        return _error_response(
            "NOT_FOUND", "Workspace not found",
            request.state.request_id, status_code=404,
        )
    return ws


@app.delete("/workspaces/{wid}")
def delete_workspace(wid: str, request: Request) -> dict[str, str]:
    db = get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(wid)
    if ws is None:
        return _error_response(
            "NOT_FOUND", "Workspace not found",
            request.state.request_id, status_code=404,
        )
    repo.soft_delete(wid)
    return {"status": "deleted"}


# --- Memory endpoints ---

@app.get("/memories")
def list_memories(
    workspace_id: str, memory_type: str = "", limit: int = 50
) -> list[dict[str, object]]:
    db = get_db()
    if memory_type:
        repo = MemoryEditRepository(db)
        return repo.list_by_type(workspace_id, memory_type, limit)
    from cogito_agent.memory import MemoryRetriever

    retriever = MemoryRetriever(db)
    return retriever.list_recent(workspace_id, limit)


@app.put("/memories/{mid}")
def update_memory(
    mid: str, workspace_id: str,
    req: MemoryUpdateRequest, request: Request,
) -> dict[str, object]:
    db = get_db()
    repo = MemoryEditRepository(db)
    result = repo.update_text(mid, workspace_id, req.text)
    if result is None:
        return _error_response(
            "NOT_FOUND", "Memory not found",
            request.state.request_id, status_code=404,
        )
    return result


@app.delete("/memories/{mid}")
def delete_memory(mid: str, workspace_id: str, request: Request) -> dict[str, str]:
    db = get_db()
    repo = MemoryEditRepository(db)
    if not repo.hard_delete(mid, workspace_id):
        return _error_response(
            "NOT_FOUND", "Memory not found",
            request.state.request_id, status_code=404,
        )
    return {"status": "deleted"}


# --- Approval endpoints ---

@app.get("/approvals")
def list_approvals(
    workspace_id: str, pending_only: bool = False
) -> list[dict[str, object]]:
    db = get_db()
    repo = ApprovalRepository(db)
    if pending_only:
        return repo.list_pending(workspace_id)
    return repo.list_by_workspace(workspace_id)


@app.post("/approvals")
def create_approval(
    workspace_id: str, actor_id: str, capability_name: str,
    operation: str = "", resource: str = "", reason: str = "",
) -> dict[str, object]:
    db = get_db()
    repo = ApprovalRepository(db)
    return repo.create(workspace_id, actor_id, capability_name,
                       operation, resource, reason)


@app.post("/approvals/{aid}/resolve")
def resolve_approval(aid: str, req: ApprovalResolveRequest, request: Request) -> dict[str, object]:
    db = get_db()
    repo = ApprovalRepository(db)
    result = repo.resolve(aid, req.decision, req.decided_by)
    if result is None:
        return _error_response(
            "NOT_FOUND", "Approval not found or already resolved",
            request.state.request_id, status_code=404,
        )
    return result


# --- Workspace settings ---

@app.get("/workspaces/{wid}/settings")
def get_workspace_settings(wid: str) -> dict[str, object]:
    repo = WorkspaceSettingsRepository(get_db())
    return repo.get(wid)


@app.put("/workspaces/{wid}/settings")
def update_workspace_settings(
    wid: str, req: WorkspaceUpdateRequest
) -> dict[str, object]:
    repo = WorkspaceSettingsRepository(get_db())
    kwargs: dict[str, str | int] = {}
    if req.name is not None:
        repo._db.connection.execute(
            "UPDATE workspaces SET name = ? WHERE id = ?", (req.name, wid)
        )
        repo._db.connection.commit()
    if req.quiet_hours_start is not None:
        kwargs["quiet_hours_start"] = req.quiet_hours_start
    if req.quiet_hours_end is not None:
        kwargs["quiet_hours_end"] = req.quiet_hours_end
    if req.timezone is not None:
        kwargs["timezone"] = req.timezone
    if req.max_daily_notifications is not None:
        kwargs["max_daily_notifications"] = req.max_daily_notifications
    return repo.upsert(wid, **kwargs)


# --- Export / Cleanup ---

@app.get("/export")
def export_workspace(workspace_id: str, request: Request) -> dict[str, object]:
    db = get_db()
    cur = db.connection.execute(
        "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
    )
    ws = cur.fetchone()
    if ws is None:
        return _error_response(
            "NOT_FOUND", "Workspace not found",
            request.state.request_id, status_code=404,
        )

    data: dict[str, object] = {
        "workspace": dict(ws),
        "sessions": [],
        "memories": [],
        "traces": [],
    }
    cur = db.connection.execute(
        "SELECT * FROM sessions WHERE workspace_id = ? AND deleted_at IS NULL",
        (workspace_id,),
    )
    data["sessions"] = [dict(r) for r in cur.fetchall()]

    cur = db.connection.execute(
        "SELECT * FROM memories WHERE workspace_id = ? AND deleted_at IS NULL",
        (workspace_id,),
    )
    data["memories"] = [dict(r) for r in cur.fetchall()]

    cur = db.connection.execute(
        "SELECT * FROM traces WHERE workspace_id = ?", (workspace_id,)
    )
    data["traces"] = [dict(r) for r in cur.fetchall()]

    return _redact_dict(data, RedactionHelper())


@app.post("/workspaces/{wid}/cleanup")
def cleanup_workspace(wid: str) -> dict[str, int]:
    db = get_db()
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    deleted_sessions = db.connection.execute(
        "DELETE FROM sessions WHERE workspace_id = ?"
        " AND deleted_at IS NOT NULL AND deleted_at < ?",
        (wid, cutoff),
    ).rowcount
    deleted_traces = db.connection.execute(
        "DELETE FROM traces WHERE workspace_id = ?"
        " AND ended_at IS NOT NULL AND ended_at < ?",
        (wid, cutoff),
    ).rowcount
    db.connection.commit()
    return {"deleted_sessions": deleted_sessions, "deleted_traces": deleted_traces}


@app.get("/skills")
def list_pool_skills() -> list[dict[str, object]]:
    pool = SkillPool(get_db())
    return pool.list_all()


@app.post("/skills")
def install_skill(req: SkillInstallRequest) -> dict[str, object]:
    pool = SkillPool(get_db())
    return pool.install(req.manifest)


@app.get("/workspaces/{wid}/skills")
def list_workspace_skills(wid: str) -> list[dict[str, object]]:
    ws_skill = WorkspaceSkill(get_db())
    return ws_skill.list_by_workspace(wid)


@app.post("/workspaces/{wid}/skills")
def install_to_workspace(
    wid: str, req: WorkspaceSkillInstall, request: Request,
) -> dict[str, object]:
    ws_skill = WorkspaceSkill(get_db())
    result = ws_skill.copy_from_pool(wid, req.pool_skill_id)
    if result is None:
        return _error_response(
            "NOT_FOUND", "Pool skill not found",
            request.state.request_id, status_code=404,
        )
    return result


@app.post("/sessions/{sid}/skills/{skill_name}/run")
def run_skill(
    sid: str, skill_name: str,
    req: RunSkillRequest, request: Request,
) -> dict[str, object]:
    db = get_db()
    ws_skill = WorkspaceSkill(db)
    skills = ws_skill.list_by_workspace(req.workspace_id)
    matches = [s for s in skills if s["name"] == skill_name and s.get("enabled")]
    if not matches:
        return _error_response(
            "NOT_FOUND",
            f"Skill '{skill_name}' not found or disabled",
            request.state.request_id, status_code=404,
        )

    manifest_json = str(matches[0].get("manifest_json", "{}"))
    manifest = SkillManifest(**json.loads(manifest_json))
    runner = SkillRunner(db)
    log = runner.run(manifest, req.workspace_id, session_id=sid, inputs=req.inputs)
    return {
        "trace_id": log.trace_id,
        "skill_id": log.skill_id,
        "status": log.status,
        "step_logs": log.step_logs,
    }


def run_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
