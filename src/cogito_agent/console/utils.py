from __future__ import annotations

from typing import Any

from fastapi import Request

from cogito_agent.console.context import MenuItem


def csrf_token_input(request: Request) -> str:
    token = getattr(request.state, "csrf_token", "")
    if not token:
        return ""
    return f'<input type="hidden" name="csrf_token" value="{token}">'


def get_db(request: Request) -> Any:
    """从 request.app.state 获取 Database，向后兼容独立 Console 和嵌入式 API 模式。

    独立 Console 模式：app.state.db 已由 console/app.py 设置。
    嵌入式 API 模式：回退到全局 get_db() 单例。
    """
    db = getattr(request.app.state, "db", None)
    if db is not None:
        return db
    from cogito_agent.storage import get_db as _get_global_db

    return _get_global_db()


def get_reader(request: Request, name: str) -> Any:
    """从 request.app.state 获取 ConsoleDataReader。

    降级策略：如果 Reader 不存在（嵌入式 API 模式），返回 None。
    """
    return getattr(request.app.state, name, None)


def menu_items() -> list[MenuItem]:
    return [
        {"label": "Dashboard", "href": "/console/", "icon": "home"},
        {"label": "Overview", "href": "/console/overview", "icon": "check"},
        {"label": "Chat", "href": "/console/chat", "icon": "chat"},
        {"label": "Inbox", "href": "/console/inbox", "icon": "inbox"},
        {"label": "Memory", "href": "/console/memory", "icon": "memory"},
        {"label": "Approvals", "href": "/console/approval", "icon": "approval"},
        {"label": "Runs", "href": "/console/runs", "icon": "trace"},
        {"label": "MCP", "href": "/console/mcp", "icon": "config"},
        {"label": "Backups", "href": "/console/backups", "icon": "artifact"},
        {"label": "Traces", "href": "/console/traces", "icon": "trace"},
        {"label": "Audit", "href": "/console/audit", "icon": "audit"},
        {"label": "Autonomy", "href": "/console/autonomy", "icon": "autonomy"},
        {"label": "Config", "href": "/console/config", "icon": "config"},
        {"label": "Doctor", "href": "/console/doctor", "icon": "doctor"},
        {"label": "Files", "href": "/console/workspace/files", "icon": "file"},
        {"label": "Artifacts", "href": "/console/artifacts", "icon": "artifact"},
        {"label": "Drift", "href": "/console/drift", "icon": "drift"},
    ]
