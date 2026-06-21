from __future__ import annotations

from typing import Protocol


class InboxOutboxPort(Protocol):
    def mark_read(self, message_id: str) -> bool: ...
    def dismiss(self, message_id: str) -> bool: ...
    def retry(self, message_id: str) -> bool: ...


class InboxFeedbackPort(Protocol):
    def record_feedback(
        self,
        decision_id: str,
        event_id: str,
        value: str,
        comment: str = "",
        workspace_id: str = "*",
        user_id: str = "",
        trace_id: str = "",
    ) -> str: ...


class InboxAuditPort(Protocol):
    def log(
        self,
        actor_id: str,
        action: str,
        resource: str,
        workspace_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        decision: str = "",
        reason: str = "",
        details: str = "{}",
        redact_details: bool = True,
    ) -> str: ...


class InboxApplicationService:
    VALID_FEEDBACK = {"useful", "not_useful", "too_many", "wrong_time", "irrelevant"}

    def __init__(
        self,
        outbox: InboxOutboxPort,
        feedback: InboxFeedbackPort,
        audit: InboxAuditPort,
    ) -> None:
        self._outbox = outbox
        self._feedback = feedback
        self._audit = audit

    def mark_read(self, item_id: str) -> bool:
        return self._outbox.mark_read(item_id)

    def dismiss(self, item_id: str, *, workspace_id: str, actor_id: str) -> bool:
        changed = self._outbox.dismiss(item_id)
        if changed:
            self._audit.log(
                actor_id=actor_id,
                action="inbox.dismiss",
                resource=f"outbox:{item_id}",
                workspace_id=workspace_id,
                decision="allow",
                reason="User dismissed notification",
            )
        return changed

    def retry(self, item_id: str, *, workspace_id: str, actor_id: str) -> bool:
        changed = self._outbox.retry(item_id)
        if changed:
            self._audit.log(
                actor_id=actor_id,
                action="inbox.retry",
                resource=f"outbox:{item_id}",
                workspace_id=workspace_id,
                decision="allow",
                reason="User requested retry",
            )
        return changed

    def feedback(
        self,
        item_id: str,
        value: str,
        *,
        workspace_id: str,
    ) -> str:
        if value not in self.VALID_FEEDBACK:
            raise ValueError(f"Invalid feedback value: {value}")
        return self._feedback.record_feedback(
            decision_id=item_id,
            event_id="",
            value=value,
            workspace_id=workspace_id,
        )
