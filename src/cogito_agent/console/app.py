"""独立 Console FastAPI app — 不依赖 RuntimeKernel。

启动时只初始化 Database + ConsoleDataReader，所有页面立即可用。
Chat 功能通过 KernelManager 惰性初始化 RuntimeKernel。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cogito_agent.storage import Database
from cogito_agent.version import APP_VERSION

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals["static_version"] = "1"


def _init_db(db_path: str = "") -> Database:
    """初始化 Database 连接并运行迁移。"""
    if db_path:
        db_path = str(Path(db_path).expanduser())
        os.environ["COGITO_DB_PATH"] = db_path
    db = Database(db_path)
    db.initialize()
    applied = db.migrate()
    if applied:
        logger.info("Applied migrations: %s", applied)
    return db


def create_console_app(
    db_path: str = "",
    *,
    mount_api_routes: bool = False,
) -> FastAPI:
    """创建独立 Console FastAPI app——不需要 RuntimeKernel。

    用法::

        app = create_console_app("~/.cogito/cogito.db")
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8080)
    """
    from cogito_agent.console.router import console_router

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # 启动时只初始化 DB + Readers（不初始化 Kernel）
        db = _init_db(db_path)
        _app.state.db = db

        # 初始化 ConsoleDataReader（纯只读，不依赖 Kernel）
        from cogito_agent.console.readers import (
            ApprovalReader,
            AuditReader,
            MemoryReader,
            SessionReader,
            SystemReader,
            TraceReader,
        )

        _app.state.session_reader = SessionReader(db)
        _app.state.memory_reader = MemoryReader(db)
        _app.state.trace_reader = TraceReader(db)
        _app.state.audit_reader = AuditReader(db)
        _app.state.system_reader = SystemReader(db)
        _app.state.approval_reader = ApprovalReader(db)

        # 初始化 KernelManager（惰性，此时不构建 Kernel）
        from cogito_agent.runtime.kernel_manager import KernelManager

        _app.state.kernel_manager = KernelManager(db)

        logger.info("Console app started (kernel not yet initialized)")

        yield

        # 关闭时清理 Kernel
        km: KernelManager | None = getattr(_app.state, "kernel_manager", None)
        if km is not None:
            km.reset()
        logger.info("Console app shutdown")

    app = FastAPI(
        title="Cogito Console",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.mount_api_routes = mount_api_routes

    # ── Static files ────────────────────────────────────────────────────
    static_dir = HERE / "static"
    if static_dir.exists():
        app.mount(
            "/console/static",
            StaticFiles(directory=str(static_dir)),
            name="console_static",
        )

    # ── Middleware: inject request-scoped DB ─────────────────────────────
    # Every existing ``from cogito_agent.storage import get_db`` call in
    # console views will automatically get the correct per-request connection.

    @app.middleware("http")
    async def db_context_middleware(request: Request, call_next):
        from cogito_agent.storage import set_request_db

        db = getattr(request.app.state, "db", None)
        if db is not None:
            set_request_db(db)
        try:
            response = await call_next(request)
        finally:
            if db is not None:
                set_request_db(None)
        return response

    # ── Console routers ────────────────────────────────────────────────
    app.include_router(console_router, prefix="/console")

    # ── Root redirect ──────────────────────────────────────────────────
    @app.get("/")
    async def root_redirect() -> HTMLResponse:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/console/")

    return app
