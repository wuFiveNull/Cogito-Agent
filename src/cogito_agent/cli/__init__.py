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


def _run_skill(args: argparse.Namespace) -> None:
    from cogito_agent.shared.skill import SkillManifest
    from cogito_agent.skill import SkillPool, SkillRunner, WorkspaceSkill
    from cogito_agent.storage import Database

    db = Database(args.db_path)
    db.initialize()
    pool = SkillPool(db)
    action = args.skill_action

    if action == "list":
        skills = pool.list_all()
        if not skills:
            print("  No skills installed.")
        else:
            print(f"  Installed skills ({len(skills)}):")
            for s in skills:
                print(f"    {s['name']} v{s['version']} - {s.get('description', '')}")
    elif action == "show":
        skill = pool.get(args.skill_name)
        if skill is None:
            print(f"  Skill '{args.skill_name}' not found.")
        else:
            print(f"  Name:        {skill['name']}")
            print(f"  Version:     {skill['version']}")
            print(f"  Description: {skill.get('description', '')}")
            manifest = SkillManifest.model_validate_json(skill.get("manifest_json", "{}"))
            print(f"  Risk Level:  {manifest.risk_level.value}")
            print(f"  Steps:       {len(manifest.steps)}")
            for step in manifest.steps:
                print(f"    - {step.id}: {step.kind.value} ({step.name})")
    elif action == "validate":
        import json as _json
        try:
            with open(args.skill_file, encoding="utf-8") as f:
                data = _json.load(f)
            manifest = SkillManifest.model_validate(data)
            print(f"  Valid skill: {manifest.name} v{manifest.version}")
            print(f"  Steps: {len(manifest.steps)}")
        except Exception as e:
            print(f"  Invalid skill: {e}")
    elif action == "import":
        import json as _json
        try:
            with open(args.skill_file, encoding="utf-8") as f:
                data = _json.load(f)
            manifest = SkillManifest.model_validate(data)
            result = pool.install(manifest)
            rid = str(result["id"])[:8]
            print(f"  Imported skill: {result['name']} v{result['version']} (id={rid})")
        except Exception as e:
            print(f"  Failed to import: {e}")
    elif action == "export":
        skill = pool.get(args.skill_name)
        if skill is None:
            print(f"  Skill '{args.skill_name}' not found.")
        else:
            import json as _json
            manifest = SkillManifest.model_validate_json(skill.get("manifest_json", "{}"))
            output = manifest.model_dump_json(indent=2)
            if args.output_path:
                with open(args.output_path, "w", encoding="utf-8") as f:
                    f.write(output)
                print(f"  Exported to {args.output_path}")
            else:
                print(output)
    elif action == "run":
        skill = pool.get(args.skill_name)
        if skill is None:
            print(f"  Skill '{args.skill_name}' not found.")
            db.close()
            return
        manifest = SkillManifest.model_validate_json(skill.get("manifest_json", "{}"))
        ws_skill = WorkspaceSkill(db)
        ws_skills = ws_skill.list_by_workspace("*")
        ws_id = ws_skills[0]["workspace_id"] if ws_skills else "default"
        inputs: dict[str, str] = {}
        if args.input_path:
            import json as _json
            with open(args.input_path, encoding="utf-8") as f:
                inputs = _json.load(f)
        runner = SkillRunner(db)
        result = runner.run(manifest, ws_id, inputs=inputs)
        print(f"  Skill run: {result.status}")
        for sl in result.step_logs:
            st = sl.get("status", "")
            sid = sl.get("step_id", "")
            out = str(sl.get("output", ""))[:80]
            print(f"    [{st}] {sid}: {out}")

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

    config_parser = sub.add_parser("config", help="View or set configuration")
    config_sub = config_parser.add_subparsers(dest="config_action", help="Config command")
    config_sub.add_parser("show", help="Show current configuration")
    config_set = config_sub.add_parser("set", help="Set a config key")
    config_set.add_argument("key", help="Config key (e.g. model.provider)")
    config_set.add_argument("value", help="Config value")

    sub.add_parser("doctor", help="Check system health")

    export_parser = sub.add_parser("export", help="Export workspace data")
    export_parser.set_defaults(db_path=None)
    export_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    export_parser.add_argument(
        "--workspace", dest="workspace_name", default="default",
        help="Workspace name or ID to export (default: default)",
    )
    export_parser.add_argument(
        "--format", dest="export_format", default="json",
        choices=["json"],
        help="Output format (default: json)",
    )
    export_parser.add_argument(
        "--out", dest="output_path", default=None,
        help="Output file path (default: stdout)",
    )
    export_parser.add_argument(
        "--include", dest="include", action="append", default=[],
        choices=["traces", "memories", "audit"],
        help="Sections to include (repeatable, default: all)",
    )
    export_parser.add_argument(
        "--no-redact", dest="redact", action="store_false", default=True,
        help="Disable secret redaction",
    )

    daemon_parser = sub.add_parser("daemon", help="Run or query the background daemon")
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_action", help="Daemon command")
    daemon_sub.add_parser("once", help="Run a single tick cycle")
    daemon_sub.add_parser("run", help="Run daemon continuously")
    daemon_sub.add_parser("status", help="Show daemon and job status")
    daemon_sub.add_parser("stop", help="Set daemon state to stopped")

    inbox_parser = sub.add_parser("inbox", help="Manage inbox items")
    inbox_parser.set_defaults(db_path=None)
    inbox_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    inbox_parser.add_argument(
        "--workspace-id", dest="workspace_id", default="*",
        help="Scope to a specific workspace",
    )
    inbox_sub = inbox_parser.add_subparsers(dest="inbox_action", help="Inbox command")
    inbox_sub.add_parser("list", help="List inbox items")
    inbox_read = inbox_sub.add_parser("read", help="Show inbox item detail")
    inbox_read.add_argument("inbox_id", help="Inbox item ID")
    inbox_mark = inbox_sub.add_parser("mark-read", help="Mark inbox item as read")
    inbox_mark.add_argument("inbox_id", help="Inbox item ID")
    inbox_sub.add_parser("clear", help="Clear all inbox items")

    skill_parser = sub.add_parser("skill", help="Manage skills")
    skill_parser.set_defaults(db_path=None)
    skill_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    skill_sub = skill_parser.add_subparsers(dest="skill_action", help="Skill command")
    skill_sub.add_parser("list", help="List installed skills")
    skill_show = skill_sub.add_parser("show", help="Show skill details")
    skill_show.add_argument("skill_name", help="Skill name")
    skill_validate = skill_sub.add_parser("validate", help="Validate a skill manifest file")
    skill_validate.add_argument("skill_file", help="Path to skill manifest JSON file")
    skill_import_cmd = skill_sub.add_parser("import", help="Import a skill from file")
    skill_import_cmd.add_argument("skill_file", help="Path to skill manifest JSON file")
    skill_export_cmd = skill_sub.add_parser(
        "export", help="Export a skill to file"
    )
    skill_export_cmd.add_argument("skill_name", help="Skill name")
    skill_export_cmd.add_argument(
        "--out", dest="output_path", default=None,
        help="Output file path",
    )
    skill_run_cmd = skill_sub.add_parser("run", help="Run a skill")
    skill_run_cmd.add_argument("skill_name", help="Skill name")
    skill_run_cmd.add_argument("--input", dest="input_path", default=None, help="Input JSON file")

    schedule_parser = sub.add_parser("schedule", help="View or create scheduled jobs")
    schedule_sub = schedule_parser.add_subparsers(dest="schedule_action", help="Schedule command")
    schedule_sub.add_parser("list", help="List all scheduled jobs")
    maint_choices = ["consolidate", "archive", "refresh_fts", "cleanup_traces", "usage"]
    sched_maint = schedule_sub.add_parser("maintenance", help="Schedule a maintenance task")
    sched_maint.add_argument("task", choices=maint_choices, help="Maintenance task")
    sched_maint.add_argument("--daily", dest="daily", type=str, default="",
                             help="Run daily at HH:MM (e.g. 03:00)")
    sched_maint.add_argument("--weekly", dest="weekly", type=str, default="",
                             help="Run weekly (e.g. sun 03:00)")

    traces_parser = sub.add_parser("traces", help="View traces")
    traces_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    traces_parser.add_argument(
        "--workspace", dest="ws_id", default="*",
        help="Workspace ID filter (default: *)",
    )
    traces_parser.add_argument(
        "--status", dest="filter_status", default="",
        help="Filter by status (e.g. completed, failed)",
    )
    traces_parser.add_argument(
        "--days", dest="filter_days", type=int, default=0,
        help="Show traces from last N days",
    )
    traces_sub = traces_parser.add_subparsers(dest="traces_action")
    traces_sub.add_parser("list", help="List traces")
    traces_show = traces_sub.add_parser("show", help="Show trace detail")
    traces_show.add_argument("trace_id", help="Trace ID")

    audit_parser = sub.add_parser("audit", help="View audit logs")
    audit_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    audit_parser.add_argument(
        "--workspace", dest="ws_id", default="*",
        help="Workspace ID filter (default: *)",
    )
    audit_sub = audit_parser.add_subparsers(dest="audit_action")
    audit_sub.add_parser("list", help="List audit logs")
    audit_show = audit_sub.add_parser("show", help="Show audit log detail")
    audit_show.add_argument("audit_id", help="Audit log ID")

    usage_parser = sub.add_parser("usage", help="Show usage summary")
    usage_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    usage_parser.add_argument(
        "--last", dest="last_period", type=str, default="7d",
        help="Time period (e.g. 7d, 30d, 1d)",
    )

    mem_parser = sub.add_parser("memory", help="Manage memories")
    mem_parser.set_defaults(db_path=None)
    mem_parser.add_argument(
        "--db", dest="db_path",
        help="SQLite database path (default: ~/.cogito/cogito.db)",
    )
    mem_parser.add_argument(
        "--workspace-id", dest="workspace_id", default=None,
        help="Scope to a specific workspace",
    )
    mem_sub = mem_parser.add_subparsers(dest="memory_action", help="Memory command")
    mem_sub.add_parser("list", help="List memories")
    mem_search = mem_sub.add_parser("search", help="Search memories")
    mem_search.add_argument("query", help="Search query")
    mem_sub.add_parser("review", help="Review pending candidates")
    mem_accept = mem_sub.add_parser("accept", help="Accept a candidate")
    mem_accept.add_argument("candidate_id", help="Candidate ID")
    mem_reject = mem_sub.add_parser("reject", help="Reject a candidate")
    mem_reject.add_argument("candidate_id", help="Candidate ID")
    mem_delete = mem_sub.add_parser("delete", help="Delete a memory")
    mem_delete.add_argument("memory_id", help="Memory ID")
    mem_pin = mem_sub.add_parser("pin", help="Pin a memory")
    mem_pin.add_argument("memory_id", help="Memory ID")
    mem_edit = mem_sub.add_parser("edit", help="Edit a memory's text")
    mem_edit.add_argument("memory_id", help="Memory ID")
    mem_edit.add_argument("--text", dest="text", required=True, help="New text")
    mem_correct = mem_sub.add_parser("correct", help="Correct a memory's text")
    mem_correct.add_argument("memory_id", help="Memory ID")
    mem_correct.add_argument("--text", dest="text", required=True, help="Corrected text")
    mem_archive = mem_sub.add_parser("archive", help="Archive a memory")
    mem_archive.add_argument("memory_id", help="Memory ID")
    mem_unarchive = mem_sub.add_parser("unarchive", help="Unarchive a memory")
    mem_unarchive.add_argument("memory_id", help="Memory ID")
    mem_unpin = mem_sub.add_parser("unpin", help="Unpin a memory")
    mem_unpin.add_argument("memory_id", help="Memory ID")
    mem_merge = mem_sub.add_parser("merge", help="Merge source memory into target memory")
    mem_merge.add_argument("source_memory_id", help="Source memory ID (will be archived)")
    mem_merge.add_argument("target_memory_id", help="Target memory ID (receives merged text)")
    mem_sub.add_parser("consolidate", help="Deduplicate memories")

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
    elif args.command == "export":
        from cogito_agent.storage.repositories import WorkspaceRepository

        from .export import export_workspace, format_export

        db = Database(db_path)
        db.initialize()
        ws_repo = WorkspaceRepository(db)
        ws_list = ws_repo.list_all()
        target = args.workspace_name
        ws_id: str | None = None
        for w in ws_list:
            if w["id"] == target or w.get("name") == target:
                ws_id = str(w["id"])
                break
        if ws_id is None and ws_list:
            ws_id = str(ws_list[0]["id"])

        if ws_id is None:
            print(f"Workspace '{args.workspace_name}' not found.")
            db.close()
            return

        include_traces = not args.include or "traces" in args.include
        include_memories = not args.include or "memories" in args.include
        include_audit = not args.include or "audit" in args.include

        data = export_workspace(
            db, ws_id,
            include_traces=include_traces,
            include_memories=include_memories,
            include_audit=include_audit,
            redact=args.redact,
        )
        output = format_export(data, args.export_format)
        if args.output_path:
            with open(args.output_path, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Exported to {args.output_path}")
        else:
            print(output)
        db.close()
    elif args.command == "daemon":
        from cogito_agent.autonomy import NotificationGate, ProactiveEngine, SchedulerEngine
        from cogito_agent.storage import Database as _Db

        _db_instance = _Db(db_path)
        _db_instance.initialize()
        sched = SchedulerEngine(_db_instance)
        gate = NotificationGate(_db_instance)
        engine = ProactiveEngine(sched, gate, tick_interval=30.0)

        if args.daemon_action == "once":
            results = engine.run_once()
            if results:
                for r in results:
                    print(f"  {r}")
            else:
                print("  No jobs to process.")
        elif args.daemon_action == "run":
            engine.run()
        elif args.daemon_action == "status":
            state = ProactiveEngine.load_status(_db_instance)
            print(f"  Daemon state: {state.get('status', 'unknown')}")
            if state.get("started_at"):
                print(f"  Started: {str(state['started_at'])[:19]}")
            if state.get("last_heartbeat"):
                print(f"  Last heartbeat: {str(state['last_heartbeat'])[:19]}")
            if state.get("crash_marker"):
                print(f"  Crash marker: {state['crash_marker']}")
            jobs = sched.list_jobs("*")
            if not jobs:
                print("  No scheduled jobs.")
            else:
                print(f"  Scheduled jobs ({len(jobs)}):")
                for j in jobs:
                    print(f"    {j.name} ({j.id[:8]}): {j.status.value} enabled={j.enabled}")
            print("  Notification gate: active")
        elif args.daemon_action == "stop":
            from datetime import UTC, datetime
            stopped = datetime.now(UTC).isoformat()
            _db_instance.connection.execute(
                "INSERT INTO daemon_state"
                " (id, status, stopped_at, graceful_shutdown_marker, updated_at)"
                " VALUES ('main', 'stopped', ?, 'cli_stop', ?)"
                " ON CONFLICT(id) DO UPDATE SET status = 'stopped',"
                " stopped_at = ?, graceful_shutdown_marker = 'cli_stop',"
                " updated_at = ?",
                (stopped, stopped, stopped, stopped),
            )
            _db_instance.connection.commit()
            print("  Daemon state set to 'stopped'.")
        _db_instance.close()
    elif args.command == "inbox":
        from cogito_agent.autonomy import NotificationGate as _NGate
        from cogito_agent.storage import Database as _InboxDb  # noqa: N814
        from cogito_agent.trace.redaction import RedactionHelper

        _idb = _InboxDb(db_path)
        _idb.initialize()
        _igate = _NGate(_idb)
        _iredactor = RedactionHelper()
        _iws = args.workspace_id

        if args.inbox_action == "list":
            items = _igate.list_inbox(_iws)
            if not items:
                print("  No inbox items.")
            else:
                print(f"  Inbox ({len(items)}):")
                for item in items:
                    iid = str(item.get("id", ""))[:8]
                    title = _iredactor.redact(str(item.get("title", "")))
                    priority = str(item.get("priority", "normal"))
                    read = " [READ]" if item.get("read_at") else ""
                    created = str(item.get("created_at", ""))[:19]
                    print(f"    {iid}  [{priority}]{read}  {title}  {created}")
        elif args.inbox_action == "read":
            ib_item = _igate.read_inbox_item(args.inbox_id)
            if not ib_item:
                print(f"  Inbox item '{args.inbox_id}' not found.")
            else:
                for k, v in ib_item.items():
                    val = _iredactor.redact(str(v)) if k in ("title", "body") else str(v)
                    print(f"    {k}: {val}")
        elif args.inbox_action == "mark-read":
            _igate.mark_inbox_read(args.inbox_id)
            print(f"  Marked {args.inbox_id} as read.")
        elif args.inbox_action == "clear":
            _igate.clear_inbox(_iws)
            print(f"  Cleared inbox for workspace '{_iws}'.")
        else:
            print("Usage: cogito inbox list|read|mark-read|clear")
        _idb.close()
    elif args.command == "schedule":
        import uuid as _uuid
        from datetime import UTC, datetime, timedelta

        from cogito_agent.autonomy import SchedulerEngine as _Sched
        from cogito_agent.shared import JobStatus, ScheduleJob
        from cogito_agent.storage import Database as _Db

        _db2 = _Db(db_path)
        _db2.initialize()
        sched = _Sched(_db2)

        if args.schedule_action == "list":
            jobs = sched.list_jobs("*")
            if not jobs:
                print("  No scheduled jobs.")
            else:
                print(f"  Scheduled jobs ({len(jobs)}):")
                for j in jobs:
                    nxt = j.next_run_at or "-"
                    print(f"    {j.name} ({j.id[:8]}): {j.status.value}"
                          f" enabled={j.enabled} next={nxt}")
        elif args.schedule_action == "maintenance":

            now = datetime.now(UTC)
            next_run: str | None = None
            schedule_type = "one_shot"
            interval_seconds: int | None = None

            if args.daily:
                schedule_type = "interval"
                interval_seconds = 86400
                parts = args.daily.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                next_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_dt <= now:
                    next_dt += timedelta(days=1)
                next_run = next_dt.isoformat()
            elif args.weekly:
                schedule_type = "interval"
                interval_seconds = 604800
                next_run = (now + timedelta(seconds=interval_seconds)).isoformat()

            job = ScheduleJob(
                id=str(_uuid.uuid4()),
                name=f"maintenance.{args.task}",
                workspace_id="*",
                actor="maintenance",
                capability_name=f"maintenance.{args.task}",
                input_json='{"workspace_id": "*"}',
                schedule_type=schedule_type,
                run_at=None,
                interval_seconds=interval_seconds,
                enabled=True,
                dry_run=False,
                max_retries=0,
                retry_count=0,
                status=JobStatus.pending,
                next_run_at=next_run or now.isoformat(),
            )
            jid = sched.schedule(job)
            print(f"  Scheduled maintenance.{args.task} as job {jid[:8]}")
            if next_run:
                print(f"  Next run: {next_run}")
        _db2.close()
    elif args.command == "traces":
        from cogito_agent.cli.replay import TraceInspector as _inspector_cls  # noqa: N813
        from cogito_agent.storage import Database as _db_cls  # noqa: N813

        _tdb = _db_cls(db_path)
        _tdb.initialize()
        _inspector = _inspector_cls(_tdb)
        ws_filter = args.ws_id
        status_filter = args.filter_status
        days_filter = args.filter_days

        if args.traces_action == "list":
            traces = _inspector.list_traces(workspace_id=ws_filter)
            if status_filter:
                traces = [t for t in traces if t.get("status") == status_filter]
            if days_filter > 0:
                from datetime import UTC, datetime, timedelta
                cutoff = (datetime.now(UTC) - timedelta(days=days_filter)).isoformat()
                traces = [t for t in traces if str(t.get("started_at", "")) >= cutoff]
            if not traces:
                print("  No traces found.")
            else:
                print(f"  Traces ({len(traces)}):")
                for t in traces:
                    tid = str(t.get("id", ""))[:16]
                    st = str(t.get("status", ""))
                    ws = str(t.get("workspace_id", ""))[:8]
                    started = str(t.get("started_at", ""))[:19]
                    print(f"    {tid}  [{st}]  ws={ws}  {started}")
        elif args.traces_action == "show":
            trace = _inspector.get_trace_full(args.trace_id)
            if trace is None:
                print(f"  Trace '{args.trace_id}' not found.")
            else:
                print(_inspector.format_trace_detail(trace))
        _tdb.close()
    elif args.command == "audit":
        from cogito_agent.storage import Database as _ADB  # noqa: N814

        _adb = _ADB(db_path)
        _adb.initialize()
        ws_filter = args.ws_id

        if args.audit_action == "list":
            if ws_filter == "*":
                cur = _adb.connection.execute(
                    "SELECT id, actor_id, action, resource, decision, created_at"
                    " FROM audit_logs ORDER BY created_at DESC LIMIT 50"
                )
            else:
                cur = _adb.connection.execute(
                    "SELECT id, actor_id, action, resource, decision, created_at"
                    " FROM audit_logs WHERE workspace_id = ?"
                    " ORDER BY created_at DESC LIMIT 50",
                    (ws_filter,),
                )
            rows = cur.fetchall()
            if not rows:
                print("  No audit logs found.")
            else:
                print(f"  Audit logs ({len(rows)}):")
                for r in rows:
                    rid = str(r["id"])[:8]
                    actor = str(r["actor_id"])
                    action = str(r["action"])
                    decision = str(r["decision"])
                    created = str(r["created_at"])[:19]
                    print(f"    {rid}  {actor}/{action}  [{decision}]  {created}")
        elif args.audit_action == "show":
            cur = _adb.connection.execute(
                "SELECT * FROM audit_logs WHERE id = ?", (args.audit_id,)
            )
            row = cur.fetchone()
            if row is None:
                print(f"  Audit log '{args.audit_id}' not found.")
            else:
                for k, v in dict(row).items():
                    print(f"    {k}: {v}")
        _adb.close()
    elif args.command == "usage":
        from cogito_agent.storage import Database as _UDB  # noqa: N814

        _udb = _UDB(db_path)
        _udb.initialize()

        days = 7
        if args.last_period.endswith("d"):
            days = int(args.last_period[:-1])
        elif args.last_period.endswith("h"):
            days = 0
        from datetime import UTC, datetime, timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        cur = _udb.connection.execute(
            "SELECT COUNT(*) as cnt FROM traces WHERE started_at >= ?",
            (cutoff,),
        )
        traces_cnt = cur.fetchone()["cnt"]

        cur = _udb.connection.execute(
            "SELECT COUNT(*) as cnt FROM model_calls mc"
            " JOIN traces t ON mc.trace_id = t.id"
            " WHERE t.started_at >= ?",
            (cutoff,),
        )
        model_calls = cur.fetchone()["cnt"]

        cur = _udb.connection.execute(
            "SELECT COUNT(*) as cnt FROM tool_calls tc"
            " JOIN traces t ON tc.trace_id = t.id"
            " WHERE t.started_at >= ?",
            (cutoff,),
        )
        tool_calls = cur.fetchone()["cnt"]

        cur = _udb.connection.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE created_at >= ?",
            (cutoff,),
        )
        messages = cur.fetchone()["cnt"]

        cur = _udb.connection.execute(
            "SELECT COUNT(*) as cnt FROM audit_logs WHERE created_at >= ?",
            (cutoff,),
        )
        audit_logs = cur.fetchone()["cnt"]

        print(f"  Usage summary (last {args.last_period}):")
        print(f"    traces:     {traces_cnt}")
        print(f"    model_calls: {model_calls}")
        print(f"    tool_calls:  {tool_calls}")
        print(f"    messages:    {messages}")
        print(f"    audit_logs:  {audit_logs}")
        _udb.close()
    elif args.command == "memory":
        ws_id = getattr(args, "workspace_id", None) or "*"
        mem_ns = argparse.Namespace(
            db_path=db_path,
            workspace_id=ws_id,
            query=getattr(args, "query", ""),
            candidate_id=getattr(args, "candidate_id", ""),
            memory_id=getattr(args, "memory_id", ""),
            text=getattr(args, "text", ""),
            source_memory_id=getattr(args, "source_memory_id", ""),
            target_memory_id=getattr(args, "target_memory_id", ""),
        )
        from .memory import (
            _run_memory_accept,
            _run_memory_archive,
            _run_memory_consolidate,
            _run_memory_correct,
            _run_memory_delete,
            _run_memory_edit,
            _run_memory_list,
            _run_memory_merge,
            _run_memory_pin,
            _run_memory_reject,
            _run_memory_review,
            _run_memory_search,
            _run_memory_unarchive,
            _run_memory_unpin,
        )
        dispatch = {
            "list": _run_memory_list,
            "search": _run_memory_search,
            "review": _run_memory_review,
            "accept": _run_memory_accept,
            "reject": _run_memory_reject,
            "delete": _run_memory_delete,
            "pin": _run_memory_pin,
            "edit": _run_memory_edit,
            "correct": _run_memory_correct,
            "archive": _run_memory_archive,
            "unarchive": _run_memory_unarchive,
            "unpin": _run_memory_unpin,
            "merge": _run_memory_merge,
            "consolidate": _run_memory_consolidate,
        }
        handler = dispatch.get(args.memory_action)
        if handler:
            handler(mem_ns)
        else:
            print(
                "Usage: cogito memory"
                " list|search|review|accept|reject|delete|pin|edit|correct"
                "|archive|unarchive|unpin|merge|consolidate"
            )
    elif args.command == "skill":
        _run_skill(argparse.Namespace(
            db_path=db_path,
            skill_action=args.skill_action,
            skill_name=getattr(args, "skill_name", ""),
            skill_file=getattr(args, "skill_file", ""),
            output_path=getattr(args, "output_path", None),
            input_path=getattr(args, "input_path", None),
        ))
    elif args.command == "config":
        from .config_manager import KEYS, get_config, set_config_key

        if args.config_action == "show":
            cfg = get_config()
            print("Current configuration (~/.cogito/config.json):")
            for k in KEYS:
                print(f"  {k} = {cfg.get(k, '')}")
        elif args.config_action == "set":
            try:
                set_config_key(args.key, args.value)
                print(f"  {args.key} = {args.value}")
            except ValueError as e:
                print(f"Error: {e}")
        else:
            print("Usage: cogito config show | cogito config set <key> <value>")
    elif args.command == "doctor":
        from cogito_agent.trace import RedactionHelper

        from .config_manager import doctor as run_doctor

        checks = run_doctor()
        redactor = RedactionHelper()
        all_ok = True
        for c in checks:
            status = c["status"]
            detail = redactor.redact(c["detail"])
            if status == "ok":
                print(f"  [  OK  ] {c['check']}: {detail}")
            elif status == "warn":
                print(f"  [ WARN ] {c['check']}: {detail}")
                all_ok = False
            else:
                print(f"  [ INFO ] {c['check']}: {detail}")
        if all_ok:
            print("All checks passed.")
    else:
        parser.print_help()
        sys.exit(1)


__all__ = [
    "run_cli",
]
