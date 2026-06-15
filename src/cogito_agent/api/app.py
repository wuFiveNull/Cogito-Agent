from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cogito_agent.mcp import MCPServerConfig
from cogito_agent.mcp.manager import MCPServerManager
from cogito_agent.models import get_adapter, list_providers
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, SkillManifest
from cogito_agent.skill import SkillPool, SkillRunner, WorkspaceSkill
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import (
    MemoryCandidateRepository,
    SessionRepository,
    WorkspaceRepository,
)


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


class CandidateAction(BaseModel):
    candidate_id: str
    action: str


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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
