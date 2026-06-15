from __future__ import annotations

import uuid

from cogito_agent.runtime import RuntimeKernel
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database, SessionRepository, WorkspaceRepository


def run_cli(db_path: str = ":memory:") -> None:
    db = Database(db_path)
    db.initialize()

    ws_repo = WorkspaceRepository(db)
    ws = ws_repo.create("default", "Default Workspace")
    workspace_id = str(ws["id"]) if not isinstance(ws["id"], str) else ws["id"]

    sess_repo = SessionRepository(db)
    sess = sess_repo.create(str(uuid.uuid4()), workspace_id, "CLI Session")
    session_id = str(sess["id"]) if not isinstance(sess["id"], str) else sess["id"]

    kernel = RuntimeKernel(db)

    print("Cogito-Agent CLI  (type 'exit' to quit, '/help' for commands)")
    print("-" * 50)

    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit", "/exit"):
            break
        if user_input.lower() == "/help":
            print("Commands: exit, /help, /approve, /deny, /memory")
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

        if result.error:
            print(f"Error: {result.error}")
        else:
            print(f"Agent: {result.output}")

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
