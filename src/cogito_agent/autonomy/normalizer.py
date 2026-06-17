from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .events import AutonomyEvent, AutonomySourceType, PriorityLevel


def normalize_from_dict(data: dict[str, Any]) -> AutonomyEvent:
    source_type_str = data.get("source_type", "system")
    try:
        source_type = AutonomySourceType(source_type_str)
    except ValueError:
        source_type = AutonomySourceType.system

    priority_str = data.get("priority", "normal")
    try:
        priority = PriorityLevel(priority_str)
    except ValueError:
        priority = PriorityLevel.normal

    event_time_raw = data.get("event_time")
    event_time: datetime | None = None
    if event_time_raw:
        if isinstance(event_time_raw, datetime):
            event_time = event_time_raw
        elif isinstance(event_time_raw, str):
            try:
                event_time = datetime.fromisoformat(event_time_raw)
            except (ValueError, TypeError):
                event_time = None

    return AutonomyEvent(
        source=data.get("source", "cli"),
        source_type=source_type,
        workspace_id=data.get("workspace_id", "*"),
        user_id=data.get("user_id", ""),
        title=data.get("title", ""),
        body=data.get("body", ""),
        created_at=data.get("created_at", datetime.now(UTC)),
        event_time=event_time,
        priority=priority,
        category=data.get("category", ""),
        dedup_key=data.get("dedup_key", ""),
        quiet_hours_override=bool(data.get("quiet_hours_override", False)),
        metadata={k: v for k, v in data.get("metadata", {}).items() if isinstance(v, str)},
    )


def _resolve_priority(value: str) -> PriorityLevel:
    try:
        return PriorityLevel(value)
    except ValueError:
        return PriorityLevel.normal


def normalize_manual(title: str, body: str, priority: str = "normal",
                     workspace_id: str = "*", category: str = "") -> AutonomyEvent:
    return AutonomyEvent(
        source="cli",
        source_type=AutonomySourceType.manual,
        workspace_id=workspace_id,
        title=title,
        body=body,
        priority=_resolve_priority(priority),
        category=category,
    )
