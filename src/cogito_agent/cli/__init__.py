import argparse
import os
import sys
from pathlib import Path

from cogito_agent.storage import Database


def _default_db_path() -> str:
    data_dir = os.path.expanduser("~/.cogito")
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(data_dir, "cogito.db")


def _run_migrate(args: argparse.Namespace) -> None:
    db = Database(args.db_path)
    db.initialize()
    applied = db.migrate()
    if applied:
        for v in applied:
            print(f"Applied migration v{v}")
    else:
        print("Already up to date.")
    db.close()


def _run_chat(args: argparse.Namespace) -> None:
    from .chat import run_cli
    run_cli(db_path=args.db_path)


def _run_replay(args: argparse.Namespace) -> None:
    from cogito_agent.storage import Database

    from .replay import TraceInspector

    db = Database(args.db_path)
    db.initialize()
    inspector = TraceInspector(db)

    if args.action == "list":
        traces = inspector.list_traces(workspace_id="*", limit=100)
        if not traces:
            print("No traces found.")
            return
        print(f"\nTraces ({len(traces)}):")
        for t in traces:
            tid = str(t.get("id", ""))[:16]
            status = str(t.get("status", ""))
            started = str(t.get("started_at", ""))[:19]
            print(f"  {tid}  [{status}]  {started}")

    elif args.action == "show":
        trace = inspector.get_trace_full(args.trace_id)
        if trace is None:
            print(f"Trace '{args.trace_id}' not found.")
            return
        print(inspector.format_trace_detail(trace))

    db.close()


def _run_maintenance(args: argparse.Namespace) -> None:
    from cogito_agent.governance import AuditLogger, PolicyEngine
    from cogito_agent.runtime.drift import DriftMaintenance
    from cogito_agent.shared import DecisionType, PolicyRequest, SpanKind
    from cogito_agent.storage import Database
    from cogito_agent.trace import Tracer

    db = Database(args.db_path)
    db.initialize()
    dm = DriftMaintenance(db)
    tracer = Tracer(db)
    audit = AuditLogger(db)
    policy = PolicyEngine()

    task = args.task
    print(f"Running maintenance: {task} ...")

    req = PolicyRequest(
        actor_id="maintenance",
        capability_name=f"maintenance.{task}",
        operation="execute",
        resource="database",
        context="background",
    )
    dec = policy.evaluate(req)
    if dec.decision == DecisionType.deny:
        print(f"Policy denied: {dec.reason}")
        audit.log(
            actor_id="maintenance", action="maintenance_denied",
            resource=f"maintenance.{task}",
            workspace_id="*", decision="deny", reason=dec.reason,
        )
        return

    trace = tracer.create_trace(
        workspace_id="*",
        root_event_id=f"maintenance.{task}",
    )
    span = tracer.create_span(trace.id, f"maintenance.{task}", SpanKind.runtime)
    error: str | None = None

    try:
        if task == "consolidate":
            count = dm.consolidate_memories(args.workspace_id)
            print(f"  Consolidated: {count} duplicate(s) removed")
        elif task == "archive":
            count = dm.archive_stale_memories(args.days)
            print(f"  Archived: {count} stale memory(s)")
        elif task == "refresh_fts":
            count = dm.refresh_fts()
            print(f"  FTS entries: {count}")
        elif task == "cleanup_traces":
            counts = dm.cleanup_traces(args.days)
            print(f"  Cleaned: {counts}")
        elif task == "usage":
            report = dm.usage_report(args.workspace_id)
            print(f"  Report: {report}")
        else:
            error = f"Unknown task: {task}"
            print(error)
    except Exception as exc:
        error = str(exc)
        print(f"  Error: {error}")

    tracer.end_span(span)
    tracer.end_trace(trace)

    audit.log(
        actor_id="maintenance", action=f"maintenance.{task}",
        resource="database", workspace_id=args.workspace_id or "*",
        trace_id=trace.id,
        decision="error" if error else "allow",
        reason=error or "ok",
    )

    db.close()


def run_cli() -> None:
    parser = argparse.ArgumentParser(
        prog="cogito",
        description="Cogito-Agent: Local-first personal Agent runtime",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    migrate_parser = sub.add_parser("migrate", help="Initialize or migrate the database")
    migrate_parser.set_defaults(db_path=None)
    migrate_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )

    chat_parser = sub.add_parser("chat", help="Start an interactive chat session")
    chat_parser.set_defaults(db_path=None)
    chat_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )

    replay_parser = sub.add_parser("replay", help="Inspect past traces")
    replay_parser.set_defaults(db_path=None)
    replay_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    replay_sub = replay_parser.add_subparsers(dest="action", help="Replay command")
    replay_sub.add_parser("list", help="List recent traces")
    replay_show = replay_sub.add_parser("show", help="Show full trace detail")
    replay_show.add_argument("trace_id", help="Trace ID to inspect")

    maint_parser = sub.add_parser("maintenance", help="Run maintenance tasks")
    maint_parser.set_defaults(db_path=None)
    maint_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    maint_parser.add_argument(
        "--workspace-id", dest="workspace_id", default=None,
        help="Scope to a specific workspace",
    )
    maint_parser.add_argument(
        "--days", type=int, default=30,
        help="Age threshold in days (for archive/cleanup)",
    )
    maint_parser.add_argument(
        "task",
        choices=["consolidate", "archive", "refresh_fts", "cleanup_traces", "usage"],
        help="Maintenance task to run",
    )

    args = parser.parse_args()

    db_path = args.db_path if args.db_path else _default_db_path()

    if args.command == "migrate":
        _run_migrate(argparse.Namespace(db_path=db_path))
    elif args.command == "chat":
        _run_chat(argparse.Namespace(db_path=db_path))
    elif args.command == "replay":
        _run_replay(argparse.Namespace(
            db_path=db_path, action=args.action, trace_id=getattr(args, "trace_id", ""),
        ))
    elif args.command == "maintenance":
        _run_maintenance(argparse.Namespace(
            db_path=db_path, task=args.task,
            workspace_id=args.workspace_id, days=args.days,
        ))
    else:
        parser.print_help()
        sys.exit(1)


__all__ = [
    "run_cli",
]
