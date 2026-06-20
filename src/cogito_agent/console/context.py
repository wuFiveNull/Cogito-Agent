from __future__ import annotations

from typing import NotRequired, TypedDict

from fastapi import Request


class Breadcrumb(TypedDict):
    label: str
    url: str


class FlashMessage(TypedDict):
    level: str
    message: str


class MenuItem(TypedDict):
    label: str
    href: str
    icon: str
    soon: NotRequired[bool]


class SystemStatusSummary(TypedDict):
    db_ok: bool
    migration_version: int
    provider: str
    streaming_enabled: bool
    timeout_seconds: int
    secrets_backend: str
    secrets_available: bool


class WorkspaceSummary(TypedDict):
    id: str
    name: str


class ConsolePageContext(TypedDict):
    request: Request
    title: str
    version: str
    workspace: WorkspaceSummary
    breadcrumbs: list[Breadcrumb]
    menu: list[MenuItem]
    flash: list[FlashMessage]
    system_status: SystemStatusSummary
    csrf_token: str
    csrf_token_input: str
