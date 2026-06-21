from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from cogito_agent.storage import Database


class DeliveryResult(BaseModel):
    message_id: str
    status: str  # sent | failed | skipped
    delivered_at: str | None = None
    error: str | None = None
    trace_id: str = ""


class DeliveryAdapter(Protocol):
    """Abstract interface for delivering outbox messages."""

    def deliver(
        self,
        message: dict[str, Any],
        db: Database,
    ) -> DeliveryResult: ...

    def adapter_name(self) -> str: ...


class LocalInboxDeliveryAdapter:
    """Delivers messages to the local inbox_items table + notifications table.

    This is the default delivery target -- messages appear in the Web Console
    Inbox and are visible via ``cogito inbox list``.
    """

    def adapter_name(self) -> str:
        return "local_inbox"

    def deliver(
        self,
        message: dict[str, Any],
        db: Database,
    ) -> DeliveryResult:
        from datetime import UTC, datetime

        from cogito_agent.autonomy.gate import NotificationGate

        mid = str(message.get("id", ""))
        ws = str(message.get("workspace_id", "*"))
        title = str(message.get("title", ""))
        body = str(message.get("body", ""))
        priority = str(message.get("priority", "normal"))
        trace_id = str(message.get("trace_id", ""))

        gate = NotificationGate(db)
        try:
            nid = gate.record_notification(
                workspace_id=ws,
                title=title,
                body=body,
                decision="push",
                priority=priority,
                trace_id=trace_id,
            )
            _ = nid
            now = datetime.now(UTC).isoformat()
            return DeliveryResult(
                message_id=mid,
                status="sent",
                delivered_at=now,
            )
        except Exception as exc:
            return DeliveryResult(
                message_id=mid,
                status="failed",
                error=str(exc),
            )


class ConsoleNotificationAdapter:
    """Delivers messages to the notifications table with inbox fallback.

    This adapter writes directly to the notifications table and also
    writes an inbox entry for the Web Console.
    """

    def adapter_name(self) -> str:
        return "console_notification"

    def deliver(
        self,
        message: dict[str, Any],
        db: Database,
    ) -> DeliveryResult:
        from datetime import UTC, datetime

        mid = str(message.get("id", ""))
        ws = str(message.get("workspace_id", "*"))
        title = str(message.get("title", ""))
        body = str(message.get("body", ""))
        priority = str(message.get("priority", "normal"))
        trace_id = str(message.get("trace_id", ""))
        decision_id = str(message.get("decision_id", ""))

        try:
            db.connection.execute(
                "INSERT INTO inbox_items"
                " (id, workspace_id, title, body, source, priority, trace_id,"
                " decision_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mid,
                    ws,
                    title,
                    body,
                    "autonomy",
                    priority,
                    trace_id or None,
                    decision_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            db.connection.commit()
            now = datetime.now(UTC).isoformat()
            return DeliveryResult(
                message_id=mid,
                status="sent",
                delivered_at=now,
            )
        except Exception as exc:
            return DeliveryResult(
                message_id=mid,
                status="failed",
                error=str(exc),
            )
