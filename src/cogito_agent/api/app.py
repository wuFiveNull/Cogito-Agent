from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cogito_agent.mcp import MCPServerConfig, MCPServerManager
from cogito_agent.models import get_adapter, list_providers
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, SkillManifest
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_db()
    get_kernel()
    yield


app = FastAPI(title="Cogito-Agent API", version="0.1.0", lifespan=lifespan)

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
    return _db


def get_kernel() -> RuntimeKernel:
    global _kernel
    if _kernel is None:
        _kernel = RuntimeKernel(get_db())
    return _kernel


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    db = get_db()
    kernel = get_kernel()
    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(req.session_id, req.workspace_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": req.text},
    )
    result = kernel.process(event)
    return ChatResponse(
        output=result.output,
        error=result.error,
        session_id=req.session_id,
        state=result.state.value if hasattr(result.state, "value") else str(result.state),
    )


@app.post("/chat/resume", response_model=ChatResponse)
def resume_chat(req: ResumeRequest) -> ChatResponse:
    db = get_db()
    kernel = get_kernel()
    repo = ApprovalRepository(db)
    approval = repo.resolve(req.approval_id, req.decision, "api")
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")
    event = RuntimeEvent(
        workspace_id=req.workspace_id,
        session_id=req.session_id,
        actor_id="user",
        source=EventSource.api,
        type=EventType.resume,
        payload={"approval_id": req.approval_id},
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
def get_trace_full(trace_id: str) -> dict[str, object]:
    from cogito_agent.cli.replay import TraceInspector

    inspector = TraceInspector(get_db())
    trace = inspector.get_trace_full(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str) -> dict[str, object]:
    db = get_db()
    cur = db.connection.execute(
        "SELECT * FROM traces WHERE id = ?", (trace_id,)
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    trace = dict(row)
    cur = db.connection.execute(
        "SELECT * FROM spans WHERE trace_id = ?", (trace_id,)
    )
    trace["spans"] = [dict(r) for r in cur.fetchall()]
    return trace


@app.post("/candidates")
def action_candidate(req: CandidateAction) -> dict[str, object]:
    db = get_db()
    repo = MemoryCandidateRepository(db)
    if req.action == "accept":
        result = repo.accept(req.candidate_id)
    elif req.action == "reject":
        result = repo.reject(req.candidate_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid action, use 'accept' or 'reject'")
    if result is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return result


class ChatStreamRequest(BaseModel):
    text: str
    session_id: str
    workspace_id: str
    provider: str = "openai"


class SkillInstallRequest(BaseModel):
    manifest: SkillManifest


class WorkspaceSkillInstall(BaseModel):
    pool_skill_id: str


class RunSkillRequest(BaseModel):
    workspace_id: str
    inputs: dict[str, str] = {}


@app.post("/chat/stream")
def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
    logger.warning("/chat/stream is EXPERIMENTAL — bypasses RuntimeKernel")
    db = get_db()
    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(req.session_id, req.workspace_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found")

    adapter = get_adapter(provider=req.provider)
    messages = [
        {"role": "user", "content": req.text},
    ]

    def event_stream() -> Generator[str, None, None]:
        full_content = ""
        for token in adapter.stream_chat(messages):
            full_content += token
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'done': True, 'content': full_content})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
            "X-Experimental": "bypasses RuntimeKernel",
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
def get_workspace(wid: str) -> dict[str, object]:
    db = get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(wid)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@app.delete("/workspaces/{wid}")
def delete_workspace(wid: str) -> dict[str, str]:
    db = get_db()
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(wid)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
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
def update_memory(mid: str, workspace_id: str, req: MemoryUpdateRequest) -> dict[str, object]:
    db = get_db()
    repo = MemoryEditRepository(db)
    result = repo.update_text(mid, workspace_id, req.text)
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@app.delete("/memories/{mid}")
def delete_memory(mid: str, workspace_id: str) -> dict[str, str]:
    db = get_db()
    repo = MemoryEditRepository(db)
    if not repo.hard_delete(mid, workspace_id):
        raise HTTPException(status_code=404, detail="Memory not found")
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
def resolve_approval(aid: str, req: ApprovalResolveRequest) -> dict[str, object]:
    db = get_db()
    repo = ApprovalRepository(db)
    result = repo.resolve(aid, req.decision, req.decided_by)
    if result is None:
        raise HTTPException(status_code=404, detail="Approval not found or already resolved")
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
def export_workspace(workspace_id: str) -> dict[str, object]:
    db = get_db()
    cur = db.connection.execute(
        "SELECT * FROM workspaces WHERE id = ?", (workspace_id,)
    )
    ws = cur.fetchone()
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

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

    return data


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
def install_to_workspace(wid: str, req: WorkspaceSkillInstall) -> dict[str, object]:
    ws_skill = WorkspaceSkill(get_db())
    result = ws_skill.copy_from_pool(wid, req.pool_skill_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return result


@app.post("/sessions/{sid}/skills/{skill_name}/run")
def run_skill(sid: str, skill_name: str, req: RunSkillRequest) -> dict[str, object]:
    db = get_db()
    ws_skill = WorkspaceSkill(db)
    skills = ws_skill.list_by_workspace(req.workspace_id)
    matches = [s for s in skills if s["name"] == skill_name and s.get("enabled")]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found or disabled")

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
