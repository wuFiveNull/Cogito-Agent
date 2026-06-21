from __future__ import annotations

from typing import Any

from cogito_agent.autonomy import (
    DecisionStore,
    FeedbackStore,
    NotificationGate,
    Outbox,
    ProactiveLoop,
    SchedulerEngine,
)
from cogito_agent.governance import AuditLogger, PolicyEngine
from cogito_agent.storage import Database
from cogito_agent.trace import RedactionHelper, Tracer


def _redact(s: str) -> str:
    return RedactionHelper().redact(s)


def _build_loop(db_path: str) -> tuple[Database, ProactiveLoop]:
    db = Database(db_path)
    db.initialize()
    tracer = Tracer(db)
    audit = AuditLogger(db)
    policy = PolicyEngine()
    gate = NotificationGate(db, policy_engine=policy, audit_logger=audit)
    sched = SchedulerEngine(
        db,
        tracer=tracer,
        audit_logger=audit,
        policy_engine=policy,
        notification_gate=gate,
    )
    dstore = DecisionStore(db)
    outbox = Outbox(db)
    fb_store = FeedbackStore(db, audit_logger=audit)
    loop = ProactiveLoop(
        scheduler=sched,
        notification_gate=gate,
        decision_store=dstore,
        outbox=outbox,
        feedback_store=fb_store,
        tracer=tracer,
        audit_logger=audit,
        policy_engine=policy,
        db=db,
    )
    return db, loop


def run_autonomy_emit(args: Any) -> None:
    db, loop = _build_loop(args.db_path)
    try:
        decision = loop.emit_event(
            title=args.title,
            body=args.body or "",
            source=args.source or "cli",
            source_type="manual",
            priority=args.priority or "normal",
            workspace_id=args.workspace_id or "*",
            category=args.category or "",
        )
        print(f"  Event:       {decision.event_id}")
        print(f"  Decision:    {decision.action.value}")
        print(f"  Reason:      {decision.reason_code}: {decision.reason}")
        print(f"  Cost score:  {decision.cost_score}")
        if decision.trace_id:
            print(f"  Trace:       {decision.trace_id}")
    finally:
        db.close()


def run_autonomy_decisions(args: Any) -> None:
    from cogito_agent.autonomy import DecisionStore

    db = Database(args.db_path)
    db.initialize()
    try:
        store = DecisionStore(db)
        decisions = store.list_decisions(
            workspace_id=args.workspace_id or "*",
            limit=args.limit or 50,
        )
        if not decisions:
            print("  No decisions found.")
            return
        print(f"  Decisions ({len(decisions)}):")
        for d in decisions:
            did = str(d.get("id", ""))
            action = str(d.get("action", "?"))
            reason = str(d.get("reason_code", ""))
            ws = str(d.get("workspace_id", ""))[:8]
            created = str(d.get("created_at", ""))[:19]
            print(f"    {did}  [{action}]  {reason}  ws={ws}  {created}")
    finally:
        db.close()


def run_autonomy_outbox(args: Any) -> None:
    db = Database(args.db_path)
    db.initialize()
    try:
        outbox = Outbox(db)
        messages = outbox.list_all(
            workspace_id=args.workspace_id or "*",
            limit=args.limit or 50,
        )
        if not messages:
            print("  No outbox messages.")
            return
        print(f"  Outbox ({len(messages)}):")
        for m in messages:
            mid = str(m.get("id", ""))
            status = str(m.get("status", "?"))
            title = _redact(str(m.get("title", ""))[:40])
            created = str(m.get("created_at", ""))[:19]
            print(f"    {mid}  [{status}]  {title}  {created}")
    finally:
        db.close()


def run_autonomy_feedback(args: Any) -> None:
    from cogito_agent.autonomy import FeedbackStore
    from cogito_agent.governance import AuditLogger

    db = Database(args.db_path)
    db.initialize()
    try:
        fb = FeedbackStore(db, audit_logger=AuditLogger(db))
        fid = fb.record_feedback(
            decision_id=args.decision_id,
            event_id="",
            value=args.value,
            comment=args.comment or "",
            workspace_id=args.workspace_id or "*",
        )
        print(f"  Feedback recorded: {fid}")
    finally:
        db.close()
