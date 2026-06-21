from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.shared import DecisionType, PolicyRequest, SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import RedactionHelper, Tracer

from .delivery import (
    DeliveryAdapter,
    DeliveryResult,
    LocalInboxDeliveryAdapter,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 3600  # 1 hour
BATCH_SIZE = 20
POLL_INTERVAL = 30  # seconds between polls


def _compute_backoff(attempt: int) -> float:
    delay: float = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
    return min(delay, float(MAX_BACKOFF_SECONDS))


class OutboxDispatcher:
    """Periodically scans pending outbox messages and delivers them.

    Features:
    - Exponential backoff with max retry
    - Delivery states: pending -> delivering -> sent | failed -> retrying -> dead_letter
    - Trace span + audit log per delivery attempt
    - Payload redaction via RedactionHelper
    - NotificationGate + PolicyEngine + AuditLogger + Tracer integration
    """

    def __init__(
        self,
        db: Database,
        delivery_adapter: DeliveryAdapter | None = None,
        policy_engine: PolicyEngine | None = None,
        audit_logger: AuditLogger | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._db = db
        self._adapter = delivery_adapter or LocalInboxDeliveryAdapter()
        self._policy = policy_engine or PolicyEngine()
        self._audit = audit_logger or AuditLogger(db)
        self._tracer = tracer or Tracer(db)
        self._redactor = RedactionHelper()
        self._running = False

    # ─── Status helpers ──────────────────────────────────────────────────────

    def _set_status(
        self,
        message_id: str,
        status: str,
        error: str = "",
        delivery_attempts: int = 0,
        next_retry_at: str = "",
    ) -> None:
        now = datetime.now(UTC).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        vals: list[Any] = [status, now]
        if error:
            fields.append("last_error = ?")
            vals.append(error[:500])
        if delivery_attempts:
            fields.append("delivery_attempts = ?")
            vals.append(delivery_attempts)
        if next_retry_at:
            fields.append("next_retry_at = ?")
            vals.append(next_retry_at)
        if status == "delivering":
            pass
        elif status == "sent":
            fields.append("delivered_at = ?")
            vals.append(now)
        elif status in ("failed", "dead_letter"):
            fields.append("failed_at = ?")
            vals.append(now)
        vals.append(message_id)
        self._db.connection.execute(
            f"UPDATE outbox_messages SET {', '.join(fields)} WHERE id = ?",
            vals,
        )
        self._db.connection.commit()

    def _pending_messages(self) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat()
        cur = self._db.connection.execute(
            "SELECT * FROM outbox_messages"
            " WHERE status IN ('pending', 'retrying')"
            "   AND (next_retry_at IS NULL OR next_retry_at <= ?)"
            " ORDER BY priority DESC, created_at ASC"
            " LIMIT ?",
            (now, BATCH_SIZE),
        )
        return [dict(r) for r in cur.fetchall()]

    # ─── Governance check ─────────────────────────────────────────────────────

    def _check_policy(self, message: dict[str, Any]) -> bool:
        req = PolicyRequest(
            actor_id="outbox_dispatcher",
            capability_name="notification.send",
            resource=f"workspace/{message.get('workspace_id', '*')}",
            operation="send",
            context="background",
        )
        decision = self._policy.evaluate(req)
        if decision.decision == DecisionType.deny:
            return False
        return True

    # ─── Single delivery attempt ──────────────────────────────────────────────

    def _deliver_one(self, message: dict[str, Any]) -> DeliveryResult:
        mid = str(message.get("id", ""))
        int(message.get("delivery_attempts", 0)) + 1
        ws = str(message.get("workspace_id", "*"))

        # Policy check
        if not self._check_policy(message):
            self._audit.log(
                actor_id="outbox_dispatcher",
                action="delivery.policy_denied",
                resource=f"outbox:{mid}",
                workspace_id=ws,
                decision="deny",
                reason="Policy denied delivery",
                redact_details=True,
            )
            return DeliveryResult(
                message_id=mid,
                status="skipped",
                error="Policy denied delivery",
            )

        # Trace and span
        trace = self._tracer.create_trace(ws, f"delivery.{mid}")
        span = self._tracer.create_span(trace.id, f"deliver.{mid}", SpanKind.autonomous)

        try:
            result = self._adapter.deliver(message, self._db)

            # Redact payload fields in audit
            safe_title = self._redactor.redact(str(message.get("title", "")))
            self._redactor.redact(str(message.get("body", "")))

            if result.status == "sent":
                self._tracer.end_span(span, "completed")
                self._tracer.end_trace(trace, "completed")
                self._audit.log(
                    actor_id="outbox_dispatcher",
                    action="delivery.sent",
                    resource=f"outbox:{mid}",
                    workspace_id=ws,
                    trace_id=trace.id,
                    decision="allow",
                    reason="Delivered successfully",
                    details=f'{{"adapter":"{self._adapter.adapter_name()}","title":"{safe_title}"}}',
                    redact_details=True,
                )
                aname = self._adapter.adapter_name()
                logger.info("Delivered outbox message %s via %s", mid[:8], aname)
            else:
                self._tracer.end_span(span, "failed")
                self._tracer.end_trace(trace, "failed")
                self._audit.log(
                    actor_id="outbox_dispatcher",
                    action="delivery.failed",
                    resource=f"outbox:{mid}",
                    workspace_id=ws,
                    trace_id=trace.id,
                    decision="error",
                    reason=result.error or "unknown",
                    details=f'{{"adapter":"{self._adapter.adapter_name()}","title":"{safe_title}"}}',
                    redact_details=True,
                )
                logger.warning("Failed delivery for outbox %s: %s", mid[:8], result.error)

            result.trace_id = trace.id
            return result

        except Exception as exc:
            self._tracer.end_span(span, "error")
            self._tracer.end_trace(trace, "error")
            safe_err = self._redactor.redact(str(exc))
            self._audit.log(
                actor_id="outbox_dispatcher",
                action="delivery.error",
                resource=f"outbox:{mid}",
                workspace_id=ws,
                trace_id=trace.id,
                decision="error",
                reason=safe_err,
                redact_details=True,
            )
            logger.exception("Delivery exception for outbox %s", mid[:8])
            return DeliveryResult(
                message_id=mid,
                status="failed",
                error=str(exc),
                trace_id=trace.id,
            )

    # ─── Process one batch ────────────────────────────────────────────────────

    def _process_message(self, message: dict[str, Any]) -> None:
        mid = str(message.get("id", ""))
        attempts = int(message.get("delivery_attempts", 0)) + 1

        # Mark as delivering
        self._set_status(mid, "delivering", delivery_attempts=attempts)

        result = self._deliver_one(message)

        if result.status == "sent":
            self._set_status(mid, "sent", delivery_attempts=attempts)
            return

        if result.status == "skipped":
            self._set_status(mid, "skipped", error=result.error or "", delivery_attempts=attempts)
            return

        # Failed — check retry eligibility
        error = result.error or ""
        if attempts >= MAX_RETRIES:
            self._set_status(mid, "dead_letter", error=error, delivery_attempts=attempts)
            self._audit.log(
                actor_id="outbox_dispatcher",
                action="delivery.dead_letter",
                resource=f"outbox:{mid}",
                workspace_id=str(message.get("workspace_id", "*")),
                decision="deny",
                reason=f"Max retries ({MAX_RETRIES}) exceeded: {error[:200]}",
                redact_details=True,
            )
            logger.warning("Outbox %s moved to dead_letter after %d attempts", mid[:8], attempts)
            return

        backoff = _compute_backoff(attempts)
        next_retry = (datetime.now(UTC) + timedelta(seconds=backoff)).isoformat()
        self._set_status(
            mid, "retrying", error=error, delivery_attempts=attempts, next_retry_at=next_retry
        )
        logger.info(
            "Outbox %s will retry in %ds (attempt %d/%d)", mid[:8], backoff, attempts, MAX_RETRIES
        )

    # ─── Public API ───────────────────────────────────────────────────────────

    def process_batch(self) -> list[str]:
        """Process one batch of pending/retrying messages. Returns processed IDs."""
        messages = self._pending_messages()
        processed: list[str] = []
        for msg in messages:
            self._process_message(msg)
            processed.append(str(msg.get("id", "")))
        return processed

    def process_all(self) -> list[str]:
        """Process all pending/retrying messages until none remain or error."""
        processed: list[str] = []
        while True:
            batch = self._pending_messages()
            if not batch:
                break
            for msg in batch:
                self._process_message(msg)
                processed.append(str(msg.get("id", "")))
        return processed

    def retry_message(self, message_id: str) -> bool:
        """Retry a single message (reset to pending)."""
        msg = self._db.connection.execute(
            "SELECT * FROM outbox_messages WHERE id = ?", (message_id,)
        ).fetchone()
        if msg is None:
            return False
        self._db.connection.execute(
            "UPDATE outbox_messages SET status = 'pending', last_error = NULL,"
            " next_retry_at = NULL WHERE id = ?",
            (message_id,),
        )
        self._db.connection.commit()
        return True

    def run_forever(self, poll_interval: float = POLL_INTERVAL) -> None:
        """Run the dispatch loop continuously (blocking)."""
        self._running = True
        logger.info("OutboxDispatcher started (poll_interval=%ss)", poll_interval)
        while self._running:
            try:
                self.process_batch()
            except Exception as exc:
                logger.exception("OutboxDispatcher batch error: %s", exc)
            time.sleep(poll_interval)

    def stop(self) -> None:
        self._running = False
