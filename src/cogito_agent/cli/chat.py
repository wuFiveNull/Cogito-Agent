from __future__ import annotations

import json
import uuid

from cogito_agent.models import get_adapter, list_providers
from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent, SkillManifest
from cogito_agent.skill import SkillRunner, WorkspaceSkill
from cogito_agent.storage import Database, SessionRepository, WorkspaceRepository


def run_cli(db_path: str = ":memory:") -> None:
    from .config_manager import get_config

    db = Database(db_path)
    db.initialize()

    ws_repo = WorkspaceRepository(db)
    ws_list = ws_repo.list_all()
    if ws_list:
        workspace_id = str(ws_list[0]["id"])
    else:
        ws = ws_repo.create("default", "Default Workspace")
        workspace_id = str(ws["id"])
    session_id = _ensure_session(db, workspace_id)

    cfg = get_config()
    current_provider = cfg.get("model.provider", "mock")
    if current_provider == "mock":
        kernel = RuntimeKernel(db)
    else:
        import os as _os

        from cogito_agent.models import get_adapter
        api_key_env = cfg.get("model.api_key_env", "MODEL_API_KEY")
        api_key = _os.environ.get(api_key_env, "")
        adapter = get_adapter(
            provider=current_provider,
            model=cfg.get("model.model", ""),
            api_key=api_key,
            base_url=cfg.get("model.base_url", ""),
        )
        kernel = RuntimeKernel(db, model_adapter=adapter)

    print("Cogito-Agent CLI  (type 'exit' to quit, '/help' for commands)")
    print("-" * 50)

    if current_provider != "mock":
        print(f"  Model provider: {current_provider}")

    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit", "/exit"):
            break
        if user_input.lower() == "/help":
            print("Commands: exit, /help, /ws list, /ws switch, /ws create, /ws delete, /memory list, /memory edit, /memory delete, /approvals, /approve, /deny, /skill list, /skill run, /trace list, /trace show, /stream, /provider, /export, /ws settings")  # noqa: E501
            continue
        if user_input.lower() == "/provider":
            provs = list_providers()
            print(f"Available providers: {', '.join(provs)}")
            print(f"Current: {current_provider}")
            continue
        if user_input.lower().startswith("/provider "):
            name = user_input[10:].strip()
            if name in list_providers():
                current_provider = name
                print(f"Switched to provider: {name}")
            else:
                print(f"Unknown provider '{name}'. Available: {', '.join(list_providers())}")
            continue
        if user_input.lower() == "/stream":
            _handle_stream(db, workspace_id, session_id, current_provider)
            continue
        if user_input.lower() == "/memory list":
            _list_all_memories(db, workspace_id)
            continue
        if user_input.lower().startswith("/memory edit "):
            _edit_memory(db, workspace_id, user_input[12:].strip())
            continue
        if user_input.lower().startswith("/memory delete "):
            _delete_memory(db, workspace_id, user_input[14:].strip())
            continue
        if user_input.lower().startswith("/approve "):
            _handle_approve(db, user_input[9:].strip())
            continue
        if user_input.lower().startswith("/deny "):
            _handle_deny(db, user_input[6:].strip())
            continue
        if user_input.lower() == "/memory":
            _show_memory_candidates(db, workspace_id)
            continue
        if user_input.lower() == "/approvals":
            _list_approvals(db, workspace_id)
            continue
        if user_input.lower() == "/export":
            _export_workspace(db, workspace_id)
            continue
        if user_input.lower() == "/ws list":
            _list_workspaces(db)
            continue
        if user_input.lower().startswith("/ws switch "):
            new_ws = _switch_workspace(db, user_input[11:].strip())
            if new_ws:
                workspace_id = new_ws
                session_id = _ensure_session(db, workspace_id)
                print(f"Switched to workspace: {workspace_id}")
            continue
        if user_input.lower().startswith("/ws create "):
            ws_repo = WorkspaceRepository(db)
            name = user_input[11:].strip()
            ws = ws_repo.create(str(uuid.uuid4()), name)
            nid = str(ws["id"])
            print(f"Created workspace: {nid} ({name})")
            workspace_id = nid
            session_id = _ensure_session(db, workspace_id)
            continue
        if user_input.lower().startswith("/ws delete "):
            ws_repo = WorkspaceRepository(db)
            target = user_input[11:].strip()
            w = ws_repo.get_by_id(target)
            if w is None:
                print(f"Workspace '{target}' not found.")
                continue
            if target == workspace_id:
                print("Cannot delete current workspace. Switch first.")
                continue
            ws_repo.soft_delete(target)
            print(f"Deleted workspace: {target}")
            continue
        if user_input.lower() == "/ws settings":
            _show_workspace_settings(db, workspace_id)
            continue
        if user_input.lower() == "/skill list":
            _list_skills(db, workspace_id)
            continue
        if user_input.lower().startswith("/skill run "):
            _run_skill(db, workspace_id, session_id, user_input[11:].strip())
            continue
        if user_input.lower() == "/trace list":
            _list_traces(db, workspace_id)
            continue
        if user_input.lower().startswith("/trace show "):
            _show_trace(db, user_input[12:].strip())
            continue
        if not user_input.strip():
            continue

        event = RuntimeEvent(
            workspace_id=workspace_id,
            session_id=session_id,
            actor_id="user",
            source=EventSource.cli,
            type=EventType.user_message,
            payload={"text": user_input},
        )

        result = kernel.process(event)

        _display_result(result, workspace_id, session_id, kernel)

    db.close()
    print("Goodbye!")


def _show_memory_candidates(db: Database, workspace_id: str) -> None:
    from cogito_agent.storage.repositories import MemoryCandidateRepository

    repo = MemoryCandidateRepository(db)
    pending = repo.list_pending(workspace_id)
    if not pending:
        print("No pending memory candidates.")
        return
    print(f"\nPending memory candidates ({len(pending)}):")
    for c in pending:
        cid = str(c.get("id", ""))
        print(f"  [{cid[:8]}] {str(c.get('text', ''))[:60]}")
    print("  Accept: /approve <id_prefix>  |  Deny: /deny <id_prefix>")


def _find_candidate(db: Database, prefix: str) -> str | None:
    cur = db.connection.execute(
        "SELECT id FROM memory_candidates WHERE status = 'pending'"
    )
    for row in cur.fetchall():
        cid = str(row["id"])
        if cid.startswith(prefix):
            return cid
    return None


def _handle_approve(db: Database, prefix: str) -> None:
    from cogito_agent.storage.repositories import MemoryCandidateRepository

    cid = _find_candidate(db, prefix)
    if not cid:
        print(f"Candidate '{prefix}' not found.")
        return
    repo = MemoryCandidateRepository(db)
    result = repo.accept(cid)
    if result:
        print(f"Accepted: {str(result.get('text', ''))[:60]}")


def _list_skills(db: Database, workspace_id: str) -> None:
    ws_skill = WorkspaceSkill(db)
    skills = ws_skill.list_by_workspace(workspace_id)
    if not skills:
        print("No skills installed in this workspace.")
        return
    print(f"\nSkills in workspace ({len(skills)}):")
    for s in skills:
        enabled = "enabled" if s.get("enabled") else "disabled"
        sname = str(s.get("name", ""))
        sversion = str(s.get("version", ""))
        sdesc = str(s.get("description", ""))
        print(f"  {sname} v{sversion} [{enabled}]  — {sdesc[:60]}")


def _run_skill(db: Database, workspace_id: str, session_id: str, args: str) -> None:
    parts = args.split()
    if not parts:
        print("Usage: /skill run <name> [k=v ...]")
        return
    skill_name = parts[0]
    inputs: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, _, v = p.partition("=")
            inputs[k] = v

    ws_skill = WorkspaceSkill(db)
    skills = ws_skill.list_by_workspace(workspace_id)
    matches = [s for s in skills if s["name"] == skill_name and s.get("enabled")]
    if not matches:
        print(f"Skill '{skill_name}' not found or not enabled in this workspace.")
        return

    manifest_json = str(matches[0].get("manifest_json", "{}"))
    manifest = SkillManifest(**json.loads(manifest_json))
    runner = SkillRunner(db)
    log = runner.run(manifest, workspace_id, session_id=session_id, inputs=inputs)
    print(f"Skill '{skill_name}' finished: {log.status}")
    for step in log.step_logs:
        print(f"  [{step['status']}] {step.get('output', '')}"[:80])


def _handle_stream(
    db: Database, workspace_id: str, session_id: str, provider: str
) -> None:
    try:
        user_input = input("Stream input: ")
    except (EOFError, KeyboardInterrupt):
        return
    if not user_input.strip():
        return

    adapter = get_adapter(provider=provider)
    messages = [{"role": "user", "content": user_input}]
    print("Agent: ", end="", flush=True)
    full = ""
    for token in adapter.stream_chat(messages):
        print(token, end="", flush=True)
        full += token
    print()

    event = RuntimeEvent(
        workspace_id=workspace_id,
        session_id=session_id,
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": user_input},
    )
    kernel = RuntimeKernel(db)
    kernel.process(event)


def _list_all_memories(db: Database, workspace_id: str) -> None:
    from cogito_agent.memory import MemoryRetriever

    retriever = MemoryRetriever(db)
    memories = retriever.list_recent(workspace_id, limit=50)
    if not memories:
        print("No memories.")
        return
    print(f"\nMemories ({len(memories)}):")
    for m in memories:
        mid = str(m.get("id", ""))[:8]
        text = str(m.get("text", ""))[:60]
        mtype = str(m.get("type", "general"))
        print(f"  [{mtype}] {mid}  {text}")


def _edit_memory(db: Database, workspace_id: str, args: str) -> None:
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        print("Usage: /memory edit <id> <new text>")
        return
    from cogito_agent.storage.repositories import MemoryEditRepository

    repo = MemoryEditRepository(db)
    result = repo.update_text(parts[0], workspace_id, parts[1])
    if result:
        print(f"Memory updated: {str(result.get('text', ''))[:60]}")
    else:
        print(f"Memory '{parts[0]}' not found.")


def _delete_memory(db: Database, workspace_id: str, mid: str) -> None:
    from cogito_agent.storage.repositories import MemoryEditRepository

    repo = MemoryEditRepository(db)
    if repo.hard_delete(mid, workspace_id):
        print(f"Memory '{mid}' deleted.")
    else:
        print(f"Memory '{mid}' not found.")


def _list_approvals(db: Database, workspace_id: str) -> None:
    from cogito_agent.storage.repositories import ApprovalRepository

    repo = ApprovalRepository(db)
    pending = repo.list_pending(workspace_id)
    if not pending:
        print("No pending approvals.")
        return
    print(f"\nPending approvals ({len(pending)}):")
    for a in pending:
        aid = str(a.get("id", ""))[:8]
        cap = str(a.get("capability_name", ""))
        op = str(a.get("operation", ""))
        print(f"  [{aid}] {cap} / {op}")


def _display_result(
    result: object, workspace_id: str, session_id: str, kernel: object,
) -> None:
    from cogito_agent.runtime import TurnResult

    tr = result
    if not isinstance(tr, TurnResult):
        print(str(result))
        return

    if tr.trace_id:
        print(f"[trace_id: {tr.trace_id[:16]}]  [state: {tr.state.value}]")

    if tr.error:
        print(f"Error: {tr.error}")

    if tr.state.value == "waiting_approval" and tr.approval_pending:
        aid = tr.approval_id or ""
        print(f"\n[Approval Required] id={aid[:8]}")
        print("  Approve? (y/N): ", end="", flush=True)
        try:
            ans = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        db = kernel._db if hasattr(kernel, "_db") else None
        if ans in ("y", "yes"):
            if db:
                from cogito_agent.storage.repositories import ApprovalRepository
                repo = ApprovalRepository(db)
                repo.resolve(aid, "approved", "user")
                print("  Approved. Resuming...")
                from cogito_agent.shared import RuntimeEvent
                resume_event = RuntimeEvent(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    actor_id="user",
                    source=EventSource.cli,
                    type=EventType.resume,
                    payload={"approval_id": aid},
                )
                resumed = kernel.resume(resume_event) if hasattr(kernel, "resume") else None
                if resumed:
                    _display_result(resumed, workspace_id, session_id, kernel)
                    return
        else:
            if db:
                from cogito_agent.storage.repositories import ApprovalRepository
                repo = ApprovalRepository(db)
                repo.resolve(aid, "denied", "user")
            print("  Denied.")
        return

    if tr.output:
        print(f"Agent: {tr.output}")

    if tr.tool_summaries:
        print()
        for ts in tr.tool_summaries:
            tool_name = str(ts.get("tool", ""))
            summary = str(ts.get("summary", ""))
            err = str(ts.get("error", ""))
            if err and err != "None":
                print(f"  \u2716 {tool_name}: {err}")
            else:
                print(f"  \u2713 {tool_name}: {summary[:60]}")

    if tr.sources:
        print()
        for s in tr.sources:
            stype = str(s.get("type", ""))
            text = str(s.get("text", ""))[:40]
            if text:
                print(f"  [{stype}] {text}")


def _export_workspace(db: Database, workspace_id: str) -> None:
    import json

    from cogito_agent.storage.repositories import WorkspaceRepository

    ws_repo = WorkspaceRepository(db)
    ws = ws_repo.get_by_id(workspace_id)
    if ws is None:
        print(f"Workspace '{workspace_id}' not found.")
        return

    cur = db.connection.execute(
        "SELECT * FROM sessions WHERE workspace_id = ? AND deleted_at IS NULL",
        (workspace_id,),
    )
    sessions = [dict(r) for r in cur.fetchall()]
    cur = db.connection.execute(
        "SELECT * FROM memories WHERE workspace_id = ? AND deleted_at IS NULL",
        (workspace_id,),
    )
    memories = [dict(r) for r in cur.fetchall()]

    data = {"workspace": ws, "sessions": sessions, "memories": memories}
    print(json.dumps(data, indent=2, default=str)[:2000])
    print(f"\n... ({len(json.dumps(data, default=str))} bytes total)")


def _show_workspace_settings(db: Database, workspace_id: str) -> None:
    from cogito_agent.storage.repositories import WorkspaceSettingsRepository

    repo = WorkspaceSettingsRepository(db)
    settings = repo.get(workspace_id)
    for k, v in settings.items():
        print(f"  {k}: {v}")


def _ensure_session(db: Database, workspace_id: str) -> str:
    repo = SessionRepository(db)
    existing = repo.list_by_workspace(workspace_id)
    if existing:
        return str(existing[0]["id"])
    sess = repo.create(str(uuid.uuid4()), workspace_id, "CLI Session")
    return str(sess["id"])


def _list_workspaces(db: Database) -> None:
    repo = WorkspaceRepository(db)
    workspaces = repo.list_all()
    if not workspaces:
        print("No workspaces.")
        return
    print(f"\nWorkspaces ({len(workspaces)}):")
    for w in workspaces:
        wid = str(w.get("id", ""))
        name = str(w.get("name", ""))
        print(f"  {wid}  ({name})")


def _switch_workspace(db: Database, target: str) -> str | None:
    repo = WorkspaceRepository(db)
    ws = repo.get_by_id(target)
    if ws is None:
        print(f"Workspace '{target}' not found. Use /ws list to see available workspaces.")
        return None
    return target


def _handle_deny(db: Database, prefix: str) -> None:
    from cogito_agent.storage.repositories import MemoryCandidateRepository

    cid = _find_candidate(db, prefix)
    if not cid:
        print(f"Candidate '{prefix}' not found.")
        return
    repo = MemoryCandidateRepository(db)
    result = repo.reject(cid)
    if result:
        print(f"Rejected: {str(result.get('text', ''))[:60]}")


def _list_traces(db: Database, workspace_id: str) -> None:
    from cogito_agent.cli.replay import TraceInspector

    inspector = TraceInspector(db)
    traces = inspector.list_traces(workspace_id)
    if not traces:
        print("No traces found.")
        return
    print(f"\nTraces ({len(traces)}):")
    for t in traces:
        tid = str(t.get("id", ""))[:12]
        status = str(t.get("status", ""))
        started = str(t.get("started_at", ""))[:19]
        print(f"  {tid}  [{status}]  {started}")


def _show_trace(db: Database, trace_id: str) -> None:
    from cogito_agent.cli.replay import TraceInspector

    inspector = TraceInspector(db)
    trace = inspector.get_trace_full(trace_id)
    if trace is None:
        print(f"Trace '{trace_id}' not found.")
        return
    print(inspector.format_trace_detail(trace))
