from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.shared import SpanKind
from cogito_agent.storage import Database
from cogito_agent.trace import Tracer

from .decision import DecisionAction, NotificationDecision
from .events import AutonomyEvent, AutonomySourceType, PriorityLevel
from .feedback import FeedbackStore
from .gate import NotificationGate
from .outbox import Outbox
from .scheduler import SchedulerEngine
from .store import DecisionStore


class ProactiveLoop:
    def __init__(
        self,
        scheduler: SchedulerEngine,
        notification_gate: NotificationGate,
        decision_store: DecisionStore | None = None,
        outbox: Outbox | None = None,
        feedback_store: FeedbackStore | None = None,
        tracer: Tracer | None = None,
        audit_logger: AuditLogger | None = None,
        policy_engine: PolicyEngine | None = None,
        db: Database | None = None,
        tick_interval: float = 30.0,
    ) -> None:
        self._scheduler = scheduler
        self._gate = notification_gate
        self._db = db or notification_gate._db
        self._decision_store = decision_store or DecisionStore(self._db)
        self._outbox = outbox or Outbox(self._db)
        self._feedback = feedback_store or FeedbackStore(self._db)
        self._tracer = tracer or Tracer(db) if db else None
        self._audit = audit_logger or AuditLogger(self._db) if self._db else None
        self._policy = policy_engine or PolicyEngine()
        self._tick_interval = tick_interval
        self._running = False

    def _update_state(self, **kwargs: str | None) -> None:
        if not kwargs or self._db is None:
            return
        now = datetime.now(UTC).isoformat()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        vals = list(kwargs.values())
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        self._db.connection.execute(
            f"INSERT INTO daemon_state (id, {cols}, updated_at)"
            f" VALUES ('main', {placeholders}, ?)"
            f" ON CONFLICT(id) DO UPDATE SET {set_clause}, updated_at = ?",
            [*vals, now, *vals, now],
        )
        self._db.connection.commit()

    def process_event(
        self,
        event: AutonomyEvent,
        config: dict[str, Any] | None = None,
    ) -> NotificationDecision:
        cfg = config or {}
        tracer = self._tracer

        trace_id = event.trace_id or str(uuid.uuid4())
        event.trace_id = trace_id

        if tracer:
            trace = tracer.create_trace(
                workspace_id=event.workspace_id,
                root_event_id=event.event_id,
            )
            trace_id = trace.id
            span = tracer.create_span(
                trace.id, f"autonomy_{event.source_type.value}",
                SpanKind.scheduler,
            )

        if self._audit:
            self._audit.log(
                actor_id=event.source or "proactive_loop",
                action="autonomy.event_received",
                resource=f"event:{event.event_id}",
                workspace_id=event.workspace_id,
                trace_id=trace_id,
                decision="allow",
                reason=f"source={event.source_type.value} priority={event.priority.value}",
                details=json.dumps({
                    "title": event.title[:80],
                    "category": event.category,
                }),
            )

        decision = self._gate.evaluate(event, cfg)
        decision.trace_id = trace_id

        self._decision_store.save_decision(
            decision_id=decision.decision_id,
            event_id=decision.event_id,
            workspace_id=decision.workspace_id,
            user_id=decision.user_id,
            action=decision.action.value,
            reason_code=decision.reason_code,
            reason=decision.reason,
            cost_score=decision.cost_score,
            priority_score=decision.priority_score,
            dedup_hit=decision.dedup_hit,
            quiet_hours_hit=decision.quiet_hours_hit,
            quota_hit=decision.quota_hit,
            requires_approval=decision.requires_approval,
            trace_id=trace_id,
        )

        if decision.action == DecisionAction.push:
            nid = self._gate.record_notification(
                workspace_id=event.workspace_id,
                title=event.title,
                body=event.body,
                decision="push",
                priority=event.priority.value,
                dedup_key=event.build_dedup_key(),
                trace_id=trace_id,
            )
            self._outbox.enqueue(
                event_id=event.event_id,
                decision_id=decision.decision_id,
                title=event.title,
                body=event.body,
                workspace_id=event.workspace_id,
                user_id=event.user_id,
                priority=event.priority.value,
                source=event.source,
                trace_id=trace_id,
            )
            if self._audit:
                self._audit.log(
                    actor_id=event.source or "proactive_loop",
                    action="autonomy.notification_pushed",
                    resource=f"notification:{nid}",
                    workspace_id=event.workspace_id,
                    trace_id=trace_id,
                    decision="allow",
                    reason=decision.reason_code,
                    details=json.dumps({
                        "event_id": event.event_id,
                        "cost_score": decision.cost_score,
                    }),
                )

        elif decision.action == DecisionAction.require_approval:
            if self._audit:
                self._audit.log(
                    actor_id=event.source or "proactive_loop",
                    action="autonomy.approval_required",
                    resource=f"event:{event.event_id}",
                    workspace_id=event.workspace_id,
                    trace_id=trace_id,
                    decision="require_approval",
                    reason=decision.reason_code,
                    details=json.dumps({"reason": decision.reason}),
                )

        if tracer:
            tracer.end_span(span)
            tracer.end_trace(trace)

        return decision

    def emit_event(
        self,
        title: str,
        body: str = "",
        source: str = "manual",
        source_type: str = "manual",
        priority: str = "normal",
        workspace_id: str = "*",
        category: str = "",
        config: dict[str, Any] | None = None,
    ) -> NotificationDecision:
        event = AutonomyEvent(
            source=source,
            source_type=(
                AutonomySourceType(source_type)
                if source_type in AutonomySourceType._value2member_map_
                else AutonomySourceType.manual
            ),
            workspace_id=workspace_id,
            title=title,
            body=body,
            priority=(
                PriorityLevel(priority)
                if priority in PriorityLevel._value2member_map_
                else PriorityLevel.normal
            ),
            category=category,
        )
        return self.process_event(event, config)

    def run(self) -> None:
        self._running = True
        started = datetime.now(UTC)
        started_iso = started.isoformat()
        print(f"[daemon] Proactive loop started at {started_iso}")
        print(f"[daemon] Tick interval: {self._tick_interval}s")

        if self._db is not None:
            cur = self._db.connection.execute(
                "SELECT status, crash_marker FROM daemon_state WHERE id = 'main'"
            )
            row = cur.fetchone()
            if row and row["status"] == "running":
                print("[daemon] WARNING: Previous instance may have crashed")
                self._update_state(
                    status="running", started_at=started_iso,
                    last_heartbeat=started_iso, crash_marker="recovered",
                )
            else:
                self._update_state(
                    status="running", started_at=started_iso,
                    last_heartbeat=started_iso,
                )

        heartbeat_counter = 0
        try:
            while self._running:
                tick_start = time.time()
                try:
                    processed = self._scheduler.tick()
                    if processed:
                        for job in processed:
                            print(
                                f"[daemon] Job '{job.name}' "
                                f"({job.id[:8]}): {job.status.value}"
                            )
                except Exception as exc:
                    print(f"[daemon] Tick error: {exc}")

                heartbeat_counter += 1
                if heartbeat_counter % 10 == 0 and self._db is not None:
                    self._update_state(
                        last_heartbeat=datetime.now(UTC).isoformat()
                    )

                elapsed = time.time() - tick_start
                sleep_time = max(0.1, self._tick_interval - elapsed)
                time.sleep(sleep_time)
        except BaseException:
            if self._db is not None:
                stopped = datetime.now(UTC).isoformat()
                self._update_state(
                    status="stopped", stopped_at=stopped, crash_marker="crash",
                )
            raise
        finally:
            if self._db is not None:
                stopped = datetime.now(UTC).isoformat()
                self._update_state(
                    status="stopped", stopped_at=stopped,
                    graceful_shutdown_marker="true",
                )
            print("[daemon] Proactive loop stopped.")

    def stop(self) -> None:
        self._running = False

    def run_once(self) -> list[str]:
        processed = self._scheduler.tick()
        return [f"{j.name} ({j.id[:8]}): {j.status.value}" for j in processed]

    @staticmethod
    def load_status(db: Database) -> dict[str, Any]:
        cur = db.connection.execute(
            "SELECT * FROM daemon_state WHERE id = 'main'"
        )
        row = cur.fetchone()
        if row is None:
            return {"status": "stopped", "started_at": None, "last_heartbeat": None}
        return dict(row)
