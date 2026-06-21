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
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from cogito_agent.application import (
    ApprovalApplicationService,
    ChatApplicationService,
    MCPApplicationService,
    WorkspaceApplicationService,
    build_runtime_kernel,
    default_workspace_path,
)
from cogito_agent.capability import CapabilityRegistry
from cogito_agent.cli.export import _redact_dict
from cogito_agent.config.loader import load_config
from cogito_agent.console import console_router, status_router
from cogito_agent.governance import AuditLogger
from cogito_agent.logging import setup_logging
from cogito_agent.mcp import MCPServerConfig, MCPServerManager, MCPTrustStore
from cogito_agent.memory import (
    MemoryApplicationService,
)
from cogito_agent.models import list_providers
from cogito_agent.models.messages import (
    ContentPart,
    FilePart,
    ImagePart,
    TextPart,
)
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, SkillManifest, StreamEventType
from cogito_agent.skill import SkillPool, SkillRunner, WorkspaceSkill
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    ApprovalRepository,
    AttachmentRepository,
    MemoryEditRepository,
    SessionRepository,
    WorkspaceRepository,
    WorkspaceSettingsRepository,
)
from cogito_agent.trace.redaction import RedactionHelper
from cogito_agent.version import APP_VERSION

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
                "RATE_LIMITED",
                "Rate limit exceeded",
                request.state.request_id,
                retryable=True,
                status_code=429,
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg = load_config()
    setup_logging(cfg.logging)
    get_db()
    get_kernel()
    yield


app = FastAPI(title="Cogito-Agent API", version=APP_VERSION, lifespan=lifespan)

_console_static = Path(__file__).resolve().parent.parent / "console" / "static"
app.mount("/console/static", StaticFiles(directory=str(_console_static)), name="console_static")
app.include_router(console_router, prefix="/console")
app.include_router(status_router, prefix="/api/v1/status")


# ── Health Endpoint ───────────────────────────────────────────────────────────


@app.get("/api/v1/health", include_in_schema=False)
async def health_endpoint() -> JSONResponse:
    status_data: dict[str, Any] = {
        "status": "ok",
        "version": APP_VERSION,
        "checks": {},
    }
    all_healthy = True

    # Check DB
    try:
        _db_check = Database()
        _db_check.initialize()
        db_ver = _db_check.current_version()
        _db_check.close()
        status_data["checks"]["database"] = {
            "status": "ok",
            "migration_version": db_ver,
        }
    except Exception as exc:
        status_data["checks"]["database"] = {
            "status": "error",
            "message": str(exc),
        }
        all_healthy = False

    # Check config
    try:
        _cfg = load_config()
        status_data["checks"]["config"] = {
            "status": "ok",
            "provider": _cfg.model.provider,
        }
    except Exception as exc:
        status_data["checks"]["config"] = {
            "status": "error",
            "message": str(exc),
        }
        all_healthy = False

    if all_healthy:
        return JSONResponse(status_code=200, content=status_data)
    return JSONResponse(status_code=503, content=status_data)


# ── Doctor endpoint ──────────────────────────────────────────────────────────


@app.get("/api/v1/doctor", include_in_schema=False)
async def doctor_api_endpoint(live: str = Query("")) -> JSONResponse:
    if live and live not in ("", "0", "false"):
        return JSONResponse(
            status_code=501,
            content={
                "status": "error",
                "version": APP_VERSION,
                "checks": [
                    {
                        "section": "provider",
                        "name": "live_check",
                        "status": "skipped",
                        "message": "Live provider check not implemented in console viewer",
                    }
                ],
                "limitations": ["Live provider check not available in console viewer"],
            },
        )
    from cogito_agent.console.doctor_views import _build_checks, _overall_status

    checks = _build_checks()
    overall = _overall_status(checks)
    return JSONResponse(
        {
            "status": overall,
            "version": APP_VERSION,
            "checks": checks,
            "limitations": [
                "No real Telegram/Feishu delivery for outbox",
                "Live provider check not run by default",
                "Config viewer is read-only in v0.8 Phase 7",
            ],
        }
    )


# ── Security Headers Middleware ──────────────────────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        return response


# ── CSRF Protection Middleware ───────────────────────────────────────────────

CSRF_EXEMPT_PATHS = {
    "/chat",
    "/chat/stream",
    "/api/v1/health",
    "/api/v1/doctor",
    "/api/v1/status",
}

CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        expected = os.environ.get("COGITO_CSRF_TOKEN", "")
        if not expected:
            return await call_next(request)
        if request.method in CSRF_SAFE_METHODS:
            return await call_next(request)
        path = request.url.path
        if any(path.startswith(p) for p in CSRF_EXEMPT_PATHS):
            return await call_next(request)
        if path.startswith("/console"):
            token = request.headers.get("X-CSRF-Token", "")
            if token and token == expected:
                return await call_next(request)
            content_type = request.headers.get("content-type", "")
            ctype = content_type
            if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
                try:
                    body = await request.body()
                    body_str = body.decode("utf-8", errors="replace")
                    if f"csrf_token={expected}" in body_str:
                        return await call_next(request)
                except Exception:
                    pass
            rid = getattr(request.state, "request_id", "")
            return _error_response(
                "CSRF_FAILED",
                "CSRF validation failed",
                rid,
                status_code=403,
            )
        return await call_next(request)


# ── CORS with allowlist ──────────────────────────────────────────────────────

CFG = load_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=CFG.security.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-CSRF-Token"],
)


# ── Exception handlers ───────────────────────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return _error_response(
        "VALIDATION_ERROR",
        str(exc.errors()),
        rid,
        status_code=422,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    rid = getattr(request.state, "request_id", "")
    return _error_response(
        "INTERNAL_ERROR",
        "Internal server error",
        rid,
        status_code=500,
    )


# ── Middleware classes ────────────────────────────────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = rid
        request.state.csrf_token = os.environ.get("COGITO_CSRF_TOKEN", rid)
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


# ── Request Body Size Limit ──────────────────────────────────────────────────


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                max_size = CFG.security.max_request_size
                if size > max_size:
                    rid = getattr(request.state, "request_id", "")
                    return _error_response(
                        "PAYLOAD_TOO_LARGE",
                        f"Request body exceeds maximum size ({max_size} bytes)",
                        rid,
                        status_code=413,
                    )
            except (ValueError, TypeError):
                pass
        return await call_next(request)


# Order: outermost first, innermost last.
# SecurityHeadersMiddleware must be outermost so all responses get security headers.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIDMiddleware)


_db: Database | None = None
_kernel: RuntimeKernel | None = None
_mcp_manager: MCPServerManager | None = None
_capability_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _capability_registry
    if _capability_registry is None:
        _capability_registry = CapabilityRegistry()
    return _capability_registry


def get_mcp_manager() -> MCPServerManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPServerManager(
            get_capability_registry(),
            trust_store=MCPTrustStore(get_db()),
        )
    return _mcp_manager


def get_mcp_service() -> MCPApplicationService:
    return MCPApplicationService(get_mcp_manager(), AuditLogger(get_db()))


def reset_application_state_for_restore() -> None:
    """Close live adapters before replacing the local SQLite database."""
    global _db, _kernel, _mcp_manager, _capability_registry
    if _mcp_manager is not None:
        for server in _mcp_manager.list_servers():
            _mcp_manager.remove_server(str(server.get("name", "")))
    if _db is not None:
        _db.close()
    _kernel = None
    _mcp_manager = None
    _capability_registry = None
    _db = None


class ContentItem(BaseModel):
    type: str = "text"
    text: str | None = None
    uri: str | None = None
    mime_type: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    workspace_id: str
    text: str | None = None
    content: list[ContentItem] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)
    preferred_role: str | None = None

    def get_content_parts(self) -> list[ContentPart]:
        """Normalize text+content into unified ContentPart list.

        Both 'text' and 'content' can be present simultaneously.
        Old clients that only send 'text' continue to work.
        New clients can send attachment_ids instead of inline content.
        """
        parts: list[ContentPart] = []
        if self.text:
            parts.append(TextPart(text=self.text))
        for item in self.content:
            ptype = item.type
            if ptype == "image":
                parts.append(
                    ImagePart(
                        uri=item.uri or "",
                        mime_type=item.mime_type or "image/png",
                        attachment_id=item.uri or "",
                    )
                )
            elif ptype == "file":
                parts.append(
                    FilePart(
                        uri=item.uri or "",
                        mime_type=item.mime_type or "application/octet-stream",
                        filename=item.text or "file",
                    )
                )
            else:
                parts.append(TextPart(text=item.text or ""))
        for att_id in self.attachment_ids:
            parts.append(
                ImagePart(
                    attachment_id=att_id,
                    uri="",
                )
            )
        return parts


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


class RebuildEmbeddingRequest(BaseModel):
    workspace_id: str = "default"
    force: bool = False
    batch_size: int = 32
    retry_failed: bool = True


class SearchExplainRequest(BaseModel):
    workspace_id: str = "default"
    session_id: str = ""
    query: str
    limit: int = 10
    include_archived: bool = False
    force_mode: str | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        db_path = os.environ.get("COGITO_DB_PATH", ":memory:")
        if db_path != ":memory:":
            db_path = str(Path(db_path).expanduser())
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _db = Database(db_path)
        _db.initialize()
        _db.migrate()
    return _db


def get_kernel() -> RuntimeKernel:
    global _kernel
    if _kernel is None:
        db = get_db()
        from cogito_agent.config.loader import build_multimodel_adapter, load_config

        cfg = load_config()
        adapter = build_multimodel_adapter(cfg)
        if adapter is None:
            from cogito_agent.cli.config_manager import build_model_adapter_from_config

            adapter = build_model_adapter_from_config()
        from cogito_agent.media import MediaProcessor
        from cogito_agent.media.vision_service import VisionObservationService

        cap_reg = get_capability_registry()
        vision_svc = VisionObservationService(db, MediaProcessor())
        # Configure vision adapter from config
        if cfg.model.vision.enabled and cfg.model.vision.provider:
            from cogito_agent.models.openai_adapter import OpenAICompatibleAdapter

            v_api_key = cfg.model.vision.api_key or ""
            if cfg.model.vision.api_key_ref:
                import os

                v_api_key = os.environ.get(cfg.model.vision.api_key_ref, "") or v_api_key
            v_adapter = OpenAICompatibleAdapter(
                api_key=v_api_key or "",
                base_url=cfg.model.vision.base_url or "",
                model=cfg.model.vision.model or "gpt-4o-mini",
                timeout_sec=cfg.model.vision.timeout_sec,
            )
            vision_svc.set_vision_adapter(
                v_adapter, provider=cfg.model.vision.provider, model=cfg.model.vision.model
            )
        vision_svc.register_with_capability_registry(cap_reg)
        from cogito_agent.media import MemeService
        from cogito_agent.workspace.artifacts import ArtifactService

        meme_svc = MemeService(db)
        if vision_svc.has_vision_capability:
            meme_svc.set_vision_service(vision_svc)
        meme_svc.register_with_capability_registry(cap_reg)
        _kernel = build_runtime_kernel(
            db,
            model_adapter=adapter,
            capability_registry=cap_reg,
            artifact_writer=ArtifactService(db),
            workspace_path=default_workspace_path(),
        )
        _kernel.set_vision_service(vision_svc)
        _kernel.set_meme_service(meme_svc)
    return _kernel


def get_chat_service() -> ChatApplicationService:
    return ChatApplicationService(get_kernel())


def get_approval_service() -> ApprovalApplicationService:
    db = get_db()
    return ApprovalApplicationService(ApprovalRepository(db), AuditLogger(db))


def get_memory_service() -> MemoryApplicationService:
    db = get_db()
    return MemoryApplicationService(db, audit=AuditLogger(db))


def get_workspace_service() -> WorkspaceApplicationService:
    db = get_db()
    return WorkspaceApplicationService(db, AuditLogger(db))


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    db = get_db()
    chat_service = get_chat_service()
    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(req.session_id, req.workspace_id)
    if sess is None:
        return _error_response(
            "NOT_FOUND",
            "Session not found",
            request.state.request_id,
            status_code=404,
        )

    content_parts = req.get_content_parts()
    text_projection = req.text or ""
    payload: dict[str, object] = {
        "text": text_projection,
        "_request_id": request.state.request_id,
        "content": [p.model_dump(exclude_none=True) for p in content_parts],
    }
    if req.preferred_role:
        payload["_preferred_role"] = req.preferred_role

    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload=payload,
    )
    result = chat_service.process(event)
    return ChatResponse(
        output=result.output,
        error=result.error,
        session_id=req.session_id,
        state=result.state.value if hasattr(result.state, "value") else str(result.state),
    )


@app.post("/chat/resume", response_model=ChatResponse)
def resume_chat(req: ResumeRequest, request: Request) -> ChatResponse:
    chat_service = get_chat_service()
    approval, _ = get_approval_service().resolve(
        req.approval_id,
        decision=req.decision,
        actor_id="api",
        workspace_id=req.workspace_id,
    )
    if approval is None:
        return _error_response(
            "NOT_FOUND",
            "Approval not found or already resolved",
            request.state.request_id,
            status_code=404,
        )
    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.resume,
        payload={"approval_id": req.approval_id, "_request_id": request.state.request_id},
    )
    result = chat_service.resume(event)
    return ChatResponse(
        output=result.output,
        error=result.error,
        session_id=req.session_id,
        state=result.state.value if hasattr(result.state, "value") else str(result.state),
    )


@app.post("/sessions")
def create_session(req: SessionCreate) -> dict[str, object]:
    return get_workspace_service().create_session(req.workspace_id, req.title)


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
            "NOT_FOUND",
            "Trace not found",
            request.state.request_id,
            status_code=404,
        )
    return trace


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str, request: Request) -> dict[str, object]:
    db = get_db()
    cur = db.connection.execute("SELECT * FROM traces WHERE id = ?", (trace_id,))
    row = cur.fetchone()
    if row is None:
        return _error_response(
            "NOT_FOUND",
            "Trace not found",
            request.state.request_id,
            status_code=404,
        )
    trace = dict(row)
    cur = db.connection.execute("SELECT * FROM spans WHERE trace_id = ?", (trace_id,))
    trace["spans"] = [dict(r) for r in cur.fetchall()]
    return trace


@app.post("/candidates")
def action_candidate(req: CandidateAction, request: Request) -> dict[str, object]:
    if req.action == "accept":
        result = get_memory_service().accept_candidate(req.candidate_id, actor_id="api")
    elif req.action == "reject":
        result = get_memory_service().reject_candidate(req.candidate_id, actor_id="api")
    else:
        return _error_response(
            "VALIDATION_ERROR",
            "Invalid action, use 'accept' or 'reject'",
            request.state.request_id,
            status_code=400,
        )
    if result is None:
        return _error_response(
            "NOT_FOUND",
            "Candidate not found",
            request.state.request_id,
            status_code=404,
        )
    return result


class ChatStreamRequest(BaseModel):
    session_id: str
    workspace_id: str
    text: str | None = None
    content: list[ContentItem] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)

    def get_content_parts(self) -> list[ContentPart]:
        parts: list[ContentPart] = []
        if self.text:
            parts.append(TextPart(text=self.text))
        for item in self.content:
            ptype = item.type
            if ptype == "image":
                parts.append(
                    ImagePart(
                        uri=item.uri or "",
                        mime_type=item.mime_type or "image/png",
                        attachment_id=item.uri or "",
                    )
                )
            elif ptype == "file":
                parts.append(
                    FilePart(
                        uri=item.uri or "",
                        mime_type=item.mime_type or "application/octet-stream",
                        filename=item.text or "file",
                    )
                )
            else:
                parts.append(TextPart(text=item.text or ""))
        for att_id in self.attachment_ids:
            parts.append(
                ImagePart(
                    attachment_id=att_id,
                    uri="",
                )
            )
        return parts


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
    chat_service = get_chat_service()
    redactor = RedactionHelper()
    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(req.session_id, req.workspace_id)
    if sess is None:
        return _error_response(
            "NOT_FOUND",
            "Session not found",
            request.state.request_id,
            status_code=404,
        )

    content_parts = req.get_content_parts()
    text_projection = req.text or ""
    payload: dict[str, object] = {
        "text": text_projection,
        "_request_id": request.state.request_id,
        "channel": "api_stream",
        "content": [p.model_dump(exclude_none=True) for p in content_parts],
    }
    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload=payload,
    )

    def event_stream() -> Generator[str, None, None]:
        rid = request.state.request_id
        try:
            from cogito_agent.cli.config_manager import get_config

            cfg = get_config()
            streaming_enabled = cfg.get("model.streaming_enabled", "true").lower() == "true"
            max_retries = int(cfg.get("model.max_retries", "2"))
            for sev in chat_service.process_stream(
                event,
                request_id=rid,
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
            err_data = json.dumps(
                {
                    "error": {
                        "code": "RUNTIME_ERROR",
                        "message": "Internal error during processing",
                        "request_id": rid,
                        "retryable": False,
                    },
                }
            )
            yield f"event: error\ndata: {err_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/attachments")
async def upload_attachment(
    request: Request,
    workspace_id: str = "",
    session_id: str = "",
) -> JSONResponse:
    """Upload an image attachment.

    Accepts multipart/form-data with a single file field 'file'.
    Returns attachment metadata including content_hash for cache matching.
    """
    rid = getattr(request.state, "request_id", "")
    if not workspace_id:
        return _error_response("VALIDATION_ERROR", "workspace_id is required", rid, status_code=400)

    try:
        form = await request.form()
    except Exception:
        return _error_response("VALIDATION_ERROR", "Invalid form data", rid, status_code=400)

    uploaded_file = form.get("file")
    if not isinstance(uploaded_file, UploadFile):
        return _error_response("VALIDATION_ERROR", "No file uploaded", rid, status_code=400)

    try:
        data = await uploaded_file.read()
    except Exception:
        return _error_response("UPLOAD_ERROR", "Failed to read uploaded file", rid, status_code=400)

    filename = getattr(uploaded_file, "filename", "") or ""

    from cogito_agent.media import MediaProcessor

    processor = MediaProcessor()
    try:
        prepared = processor.validate_and_prepare(data, filename=filename)
    except Exception as e:
        safe_msg = str(e)
        if "size exceeds" in safe_msg.lower():
            return _error_response("ATTACHMENT_TOO_LARGE", safe_msg, rid, status_code=413)
        if "unsupported" in safe_msg.lower():
            return _error_response("UNSUPPORTED_MEDIA_TYPE", safe_msg, rid, status_code=415)
        if "corrupt" in safe_msg.lower() or "cannot open" in safe_msg.lower():
            return _error_response("CORRUPT_IMAGE", safe_msg, rid, status_code=400)
        return _error_response("VALIDATION_ERROR", safe_msg, rid, status_code=400)

    import hashlib

    content_hash = hashlib.sha256(data).hexdigest()

    ws_dir = Path(CFG.app.data_dir).expanduser() / "attachments" / workspace_id
    ws_dir.mkdir(parents=True, exist_ok=True)

    att_id = f"att_{uuid.uuid4().hex[:24]}"
    storage_path = str(ws_dir / f"{att_id}.jpg")
    Path(storage_path).write_bytes(prepared.data)

    repo = AttachmentRepository(get_db())
    repo.create(
        att_id=att_id,
        workspace_id=workspace_id,
        content_hash=content_hash,
        media_type=prepared.original_mime,
        original_filename=filename or "unknown",
        storage_path=storage_path,
        size_bytes=len(data),
        width=prepared.width,
        height=prepared.height,
        session_id=session_id or None,
    )

    return JSONResponse(
        {
            "attachment_id": att_id,
            "content_hash": content_hash,
            "media_type": prepared.original_mime,
            "size_bytes": len(data),
            "width": prepared.width,
            "height": prepared.height,
        }
    )


@app.get("/attachments")
def list_attachments(workspace_id: str) -> list[dict[str, object]]:
    repo = AttachmentRepository(get_db())
    return repo.list_by_workspace(workspace_id)


@app.get("/attachments/{att_id}")
def get_attachment(att_id: str, workspace_id: str, request: Request) -> dict[str, object]:
    repo = AttachmentRepository(get_db())
    att = repo.get_by_id(att_id, workspace_id)
    if att is None:
        return _error_response(
            "NOT_FOUND", "Attachment not found", request.state.request_id, status_code=404
        )
    return att


@app.get("/providers")
def list_model_providers() -> dict[str, object]:
    return {"providers": list_providers()}


@app.get("/mcp/servers")
def list_mcp_servers() -> list[dict[str, object]]:
    return get_mcp_service().list_servers()


@app.post("/mcp/servers")
def add_mcp_server(config: MCPServerConfig) -> dict[str, str]:
    get_mcp_service().add(config, name=config.name, workspace_id="default")
    return {"status": "pending_trust", "name": config.name}


@app.post("/mcp/servers/{name}/trust")
def trust_mcp_server(name: str) -> dict[str, object]:
    trusted = get_mcp_service().trust(name, workspace_id="default", actor_id="api")
    return {"status": "trusted" if trusted else "not_found", "name": name}


class MCPToolGrantRequest(BaseModel):
    schema_hash: str
    allowed_sources: list[str] = Field(default_factory=lambda: ["interactive"])
    requires_approval: bool = True


@app.post("/mcp/servers/{name}/tools/{tool_name}/grant")
def grant_mcp_tool(
    name: str,
    tool_name: str,
    request: MCPToolGrantRequest,
) -> dict[str, object]:
    granted = get_mcp_service().grant(
        name,
        tool_name,
        schema_hash=request.schema_hash,
        allowed_sources=request.allowed_sources,
        requires_approval=request.requires_approval,
        workspace_id="default",
        actor_id="api",
    )
    return {
        "status": "granted" if granted else "schema_mismatch",
        "name": name,
        "tool_name": tool_name,
    }


@app.delete("/mcp/servers/{name}")
def remove_mcp_server(name: str) -> dict[str, str]:
    get_mcp_service().remove(name, workspace_id="default")
    return {"status": "removed", "name": name}


@app.post("/mcp/sync")
def sync_mcp_servers() -> dict[str, object]:
    result = get_mcp_service().sync()
    return {
        "status": "ok",
        "discovered": result["discovered"],
        "reconnected": result["reconnected"],
    }


@app.get("/mcp/discover")
def discover_mcp_configs(config_dir: str) -> list[dict[str, object]]:
    from cogito_agent.mcp import MCPServerConfig

    configs = MCPServerConfig.load_from_directory(config_dir)
    result: list[dict[str, object]] = []
    for config in configs:
        item = config.model_dump()
        item["env"] = {key: "[REDACTED]" for key in config.env}
        result.append(item)
    return result


# --- Workspace management ---


@app.get("/workspaces")
def list_workspaces() -> list[dict[str, object]]:
    db = get_db()
    repo = WorkspaceRepository(db)
    return repo.list_all()


@app.post("/workspaces")
def create_workspace(name: str) -> dict[str, object]:
    return get_workspace_service().create_workspace(name)


@app.get("/workspaces/{wid}")
def get_workspace(wid: str, request: Request) -> dict[str, object]:
    db = get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(wid)
    if ws is None:
        return _error_response(
            "NOT_FOUND",
            "Workspace not found",
            request.state.request_id,
            status_code=404,
        )
    return ws


@app.delete("/workspaces/{wid}")
def delete_workspace(wid: str, request: Request) -> dict[str, str]:
    if not get_workspace_service().delete_workspace(wid):
        return _error_response(
            "NOT_FOUND",
            "Workspace not found",
            request.state.request_id,
            status_code=404,
        )
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
    mid: str,
    workspace_id: str,
    req: MemoryUpdateRequest,
    request: Request,
) -> dict[str, object]:
    if not get_memory_service().edit_memory(mid, workspace_id, req.text, actor_id="api"):
        return _error_response(
            "NOT_FOUND",
            "Memory not found",
            request.state.request_id,
            status_code=404,
        )
    from cogito_agent.storage.repositories import MemoryRepository

    result = MemoryRepository(get_db()).get_by_id(mid, workspace_id)
    return result or {}


@app.delete("/memories/{mid}")
def delete_memory(mid: str, workspace_id: str, request: Request) -> dict[str, str]:
    if not get_memory_service().delete_memory(mid, workspace_id, actor_id="api"):
        return _error_response(
            "NOT_FOUND",
            "Memory not found",
            request.state.request_id,
            status_code=404,
        )
    return {"status": "deleted"}


# --- Memory Embedding endpoints ---


@app.get("/memories/embeddings/status")
def memory_embeddings_status(workspace_id: str = "default") -> dict[str, object]:
    db = get_db()
    from cogito_agent.config import Settings
    from cogito_agent.embedding import MemoryEmbeddingIndexService
    from cogito_agent.retrieval.service import create_retrieval_service as _make_retrieval

    cfg = Settings.get()
    svc = _make_retrieval(db, config=cfg.memory)
    provider = svc.provider
    if provider is None:
        return {"provider": "disabled", "status": "sparse_only"}
    idx_svc = MemoryEmbeddingIndexService(db, provider)
    return idx_svc.status(workspace_id)


@app.post("/memories/embeddings/rebuild")
def memory_embeddings_rebuild(
    req: RebuildEmbeddingRequest,
) -> dict[str, object]:
    db = get_db()
    from cogito_agent.config import Settings
    from cogito_agent.embedding import MemoryEmbeddingIndexService
    from cogito_agent.retrieval.service import create_retrieval_service as _make_retrieval

    cfg = Settings.get()
    svc = _make_retrieval(db, config=cfg.memory)
    provider = svc.provider
    if provider is None:
        return {"status": "error", "message": "No embedding provider configured"}
    idx_svc = MemoryEmbeddingIndexService(db, provider)
    if req.retry_failed:
        idx_svc.retry_failed(req.workspace_id)
    return idx_svc.rebuild_workspace(req.workspace_id, force=req.force, batch_size=req.batch_size)


@app.post("/memories/search/explain")
def memory_search_explain(
    req: SearchExplainRequest,
) -> dict[str, object]:
    db = get_db()
    from cogito_agent.config import Settings
    from cogito_agent.retrieval.service import create_retrieval_service as _make_retrieval

    cfg = Settings.get()
    svc = _make_retrieval(db, config=cfg.memory)
    return svc.explain_search(
        req.workspace_id,
        req.query,
        limit=req.limit,
    )


# --- Approval endpoints ---


@app.get("/approvals")
def list_approvals(workspace_id: str, pending_only: bool = False) -> list[dict[str, object]]:
    db = get_db()
    repo = ApprovalRepository(db)
    if pending_only:
        return repo.list_pending(workspace_id)
    return repo.list_by_workspace(workspace_id)


@app.post("/approvals")
def create_approval(
    workspace_id: str,
    actor_id: str,
    capability_name: str,
    operation: str = "",
    resource: str = "",
    reason: str = "",
) -> dict[str, object]:
    return get_approval_service().create(
        workspace_id=workspace_id,
        actor_id=actor_id,
        capability_name=capability_name,
        operation=operation,
        resource=resource,
        reason=reason,
    )


@app.post("/approvals/{aid}/resolve")
def resolve_approval(aid: str, req: ApprovalResolveRequest, request: Request) -> dict[str, object]:
    result, _ = get_approval_service().resolve(
        aid,
        decision=req.decision,
        actor_id=req.decided_by,
        workspace_id="default",
    )
    if result is None:
        return _error_response(
            "NOT_FOUND",
            "Approval not found or already resolved",
            request.state.request_id,
            status_code=404,
        )
    return result


# --- Workspace settings ---


@app.get("/workspaces/{wid}/settings")
def get_workspace_settings(wid: str) -> dict[str, object]:
    repo = WorkspaceSettingsRepository(get_db())
    return repo.get(wid)


@app.put("/workspaces/{wid}/settings")
def update_workspace_settings(wid: str, req: WorkspaceUpdateRequest) -> dict[str, object]:
    return get_workspace_service().update_settings(
        wid,
        name=req.name,
        quiet_hours_start=req.quiet_hours_start,
        quiet_hours_end=req.quiet_hours_end,
        timezone=req.timezone,
        max_daily_notifications=req.max_daily_notifications,
    )


# --- Export / Cleanup ---


@app.get("/export")
def export_workspace(workspace_id: str, request: Request) -> dict[str, object]:
    db = get_db()
    cur = db.connection.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
    ws = cur.fetchone()
    if ws is None:
        return _error_response(
            "NOT_FOUND",
            "Workspace not found",
            request.state.request_id,
            status_code=404,
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

    cur = db.connection.execute("SELECT * FROM traces WHERE workspace_id = ?", (workspace_id,))
    data["traces"] = [dict(r) for r in cur.fetchall()]

    return _redact_dict(data, RedactionHelper())


@app.post("/workspaces/{wid}/cleanup")
def cleanup_workspace(wid: str) -> dict[str, int]:
    return get_workspace_service().cleanup(wid)


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
    wid: str,
    req: WorkspaceSkillInstall,
    request: Request,
) -> dict[str, object]:
    ws_skill = WorkspaceSkill(get_db())
    result = ws_skill.copy_from_pool(wid, req.pool_skill_id)
    if result is None:
        return _error_response(
            "NOT_FOUND",
            "Pool skill not found",
            request.state.request_id,
            status_code=404,
        )
    return result


@app.post("/sessions/{sid}/skills/{skill_name}/run")
def run_skill(
    sid: str,
    skill_name: str,
    req: RunSkillRequest,
    request: Request,
) -> dict[str, object]:
    db = get_db()
    ws_skill = WorkspaceSkill(db)
    skills = ws_skill.list_by_workspace(req.workspace_id)
    matches = [s for s in skills if s["name"] == skill_name and s.get("enabled")]
    if not matches:
        return _error_response(
            "NOT_FOUND",
            f"Skill '{skill_name}' not found or disabled",
            request.state.request_id,
            status_code=404,
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


# ── Meme API Endpoints ─────────────────────────────────────────────────────


class CreateMemeRequest(BaseModel):
    attachment_id: str
    name: str
    description: str
    aliases: list[str] = []
    emotions: list[str] = []
    use_cases: list[str] = []
    avoid_cases: list[str] = []
    text_on_image: str | None = None
    workspace_id: str = ""
    session_id: str = ""


class UpdateMemeRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    emotions: list[str] | None = None
    use_cases: list[str] | None = None
    avoid_cases: list[str] | None = None
    text_on_image: str | None = None
    enabled: bool | None = None


class AnalyzeMemeRequest(BaseModel):
    attachment_id: str
    force_refresh: bool = False
    workspace_id: str = ""


class SendMemeRequest(BaseModel):
    caption: str = ""
    workspace_id: str = ""


@app.post("/memes", response_model=None)
def create_meme(req: CreateMemeRequest, request: Request) -> dict[str, object] | JSONResponse:
    get_db()
    kernel = get_kernel()
    meme_svc = getattr(kernel, "_meme_service", None)
    if meme_svc is None:
        return _error_response(
            "CONFIG", "Meme service not available", request.state.request_id, status_code=503
        )
    ws = req.workspace_id or "default"
    try:
        meme = meme_svc.register_meme(
            attachment_id=req.attachment_id,
            name=req.name,
            description=req.description,
            workspace_id=ws,
            aliases=req.aliases,
            emotions=req.emotions,
            use_cases=req.use_cases,
            avoid_cases=req.avoid_cases,
            text_on_image=req.text_on_image,
        )
        return {
            "id": meme.id,
            "name": meme.name,
            "description": meme.description,
            "source": meme.source,
            "enabled": meme.enabled,
        }
    except (ValueError, RuntimeError) as e:
        return _error_response("ERROR", str(e), request.state.request_id, status_code=400)


@app.get("/memes", response_model=None)
def list_memes(
    request: Request,
    workspace_id: str = Query("default"),
    enabled_only: bool = Query(True),
    search: str = Query(""),
) -> list[dict[str, object]] | JSONResponse:
    from cogito_agent.storage import MemeAssetRepository

    repo = MemeAssetRepository(get_db())
    try:
        if search:
            return repo.search(workspace_id, search)
        if enabled_only:
            return repo.list_enabled(workspace_id)
        return repo.list_all(workspace_id)
    except Exception as e:
        return _error_response("ERROR", str(e), request.state.request_id, status_code=400)


@app.get("/memes/{meme_id}", response_model=None)
def get_meme(
    meme_id: str, request: Request, workspace_id: str = Query("default")
) -> dict[str, object] | JSONResponse:
    from cogito_agent.storage import MemeAssetRepository

    repo = MemeAssetRepository(get_db())
    record = repo.get(meme_id, workspace_id)
    if record is None:
        return _error_response(
            "NOT_FOUND", "Meme not found", request.state.request_id, status_code=404
        )
    safe = dict(record)
    safe.pop("storage_path", None)
    return safe


@app.patch("/memes/{meme_id}", response_model=None)
def update_meme(
    meme_id: str,
    req: UpdateMemeRequest,
    request: Request,
    workspace_id: str = Query("default"),
) -> dict[str, object] | JSONResponse:
    import json

    from cogito_agent.storage import MemeAssetRepository

    repo = MemeAssetRepository(get_db())
    kwargs: dict[str, object] = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.description is not None:
        kwargs["description"] = req.description
    if req.aliases is not None:
        kwargs["aliases_json"] = json.dumps(req.aliases, ensure_ascii=False)
    if req.emotions is not None:
        kwargs["emotions_json"] = json.dumps(req.emotions, ensure_ascii=False)
    if req.use_cases is not None:
        kwargs["use_cases_json"] = json.dumps(req.use_cases, ensure_ascii=False)
    if req.avoid_cases is not None:
        kwargs["avoid_cases_json"] = json.dumps(req.avoid_cases, ensure_ascii=False)
    if req.text_on_image is not None:
        kwargs["text_on_image"] = req.text_on_image
    if req.enabled is not None:
        kwargs["enabled"] = 1 if req.enabled else 0
    result = repo.update(meme_id, workspace_id, **kwargs)
    if result is None:
        return _error_response(
            "NOT_FOUND", "Meme not found", request.state.request_id, status_code=404
        )
    return result


@app.delete("/memes/{meme_id}", response_model=None)
def delete_meme(
    meme_id: str,
    request: Request,
    workspace_id: str = Query("default"),
) -> dict[str, object] | JSONResponse:
    from cogito_agent.storage import MemeAssetRepository

    repo = MemeAssetRepository(get_db())
    if repo.delete(meme_id, workspace_id):
        return {"status": "deleted", "meme_id": meme_id}
    return _error_response("NOT_FOUND", "Meme not found", request.state.request_id, status_code=404)


@app.post("/memes/analyze", response_model=None)
def analyze_meme_api(req: AnalyzeMemeRequest, request: Request) -> dict[str, object] | JSONResponse:
    kernel = get_kernel()
    meme_svc = getattr(kernel, "_meme_service", None)
    if meme_svc is None:
        return _error_response(
            "CONFIG", "Meme service not available", request.state.request_id, status_code=503
        )
    ws = req.workspace_id or "default"
    try:
        meme = meme_svc.analyze_meme(
            attachment_id=req.attachment_id,
            workspace_id=ws,
            force_refresh=req.force_refresh,
        )
        return {
            "id": meme.id,
            "name": meme.name,
            "source": meme.source,
            "description": meme.description,
            "emotions": meme.emotions,
            "use_cases": meme.use_cases,
        }
    except (ValueError, RuntimeError) as e:
        return _error_response("ERROR", str(e), request.state.request_id, status_code=400)


@app.post("/memes/{meme_id}/send", response_model=None)
def send_meme_api(
    meme_id: str,
    req: SendMemeRequest,
    request: Request,
    workspace_id: str = Query("default"),
) -> dict[str, object] | JSONResponse:
    kernel = get_kernel()
    meme_svc = getattr(kernel, "_meme_service", None)
    if meme_svc is None:
        return _error_response(
            "CONFIG", "Meme service not available", request.state.request_id, status_code=503
        )
    ws = req.workspace_id or workspace_id or "default"
    try:
        result = meme_svc.send_meme(meme_id, ws, caption=req.caption)
        safe = {
            "meme_id": result["meme_id"],
            "name": result["name"],
            "attachment_id": result["attachment_id"],
            "media_type": result["media_type"],
            "caption": result["caption"],
            "vision_model_called": result["vision_model_called"],
        }
        return safe
    except (ValueError, RuntimeError) as e:
        return _error_response("ERROR", str(e), request.state.request_id, status_code=400)


def run_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    global _db

    import uvicorn

    if _db is None:
        config = load_config()
        db_path = str(Path(config.storage.db_path).expanduser())
        os.environ["COGITO_DB_PATH"] = db_path
        get_db()
    uvicorn.run(app, host=host, port=port)
