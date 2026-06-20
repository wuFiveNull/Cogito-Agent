from __future__ import annotations

from fastapi import Request

from cogito_agent.console.context import MenuItem


def csrf_token_input(request: Request) -> str:
    token = getattr(request.state, "csrf_token", "")
    if not token:
        return ""
    return f'<input type="hidden" name="csrf_token" value="{token}">'


def menu_items() -> list[MenuItem]:
    return [
        {"label": "Dashboard", "href": "/console/", "icon": "home"},
        {"label": "Overview", "href": "/console/overview", "icon": "check"},
        {"label": "Chat", "href": "/console/chat", "icon": "chat"},
        {"label": "Inbox", "href": "/console/inbox", "icon": "inbox"},
        {"label": "Memory", "href": "/console/memory", "icon": "memory"},
        {"label": "Approvals", "href": "/console/approval", "icon": "approval"},
        {"label": "Traces", "href": "/console/traces", "icon": "trace"},
        {"label": "Audit", "href": "/console/audit", "icon": "audit"},
        {"label": "Autonomy", "href": "/console/autonomy", "icon": "autonomy"},
        {"label": "Config", "href": "/console/config", "icon": "config"},
        {"label": "Doctor", "href": "/console/doctor", "icon": "doctor"},
        {"label": "Files", "href": "/console/workspace/files", "icon": "file"},
        {"label": "Artifacts", "href": "/console/artifacts", "icon": "artifact"},
        {"label": "Drift", "href": "/console/drift", "icon": "drift"},
    ]
