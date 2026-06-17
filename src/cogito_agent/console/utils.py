from __future__ import annotations


def menu_items() -> list[dict[str, str | bool]]:
    return [
        {"label": "Dashboard", "href": "/console/", "icon": "home"},
        {"label": "Chat", "href": "/console/chat", "icon": "chat"},
        {"label": "Memory", "href": "/console/memory", "icon": "memory"},
        {"label": "Approvals", "href": "/console/approval", "icon": "approval"},
        {"label": "Traces", "href": "/console/traces", "icon": "trace"},
        {"label": "Audit", "href": "/console/audit", "icon": "audit"},
        {"label": "Autonomy", "href": "/console/autonomy", "icon": "autonomy", "soon": True},
        {"label": "Config", "href": "/console/config", "icon": "config", "soon": True},
        {"label": "Doctor", "href": "/console/doctor", "icon": "doctor", "soon": True},
    ]
