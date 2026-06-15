from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
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


def run_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
