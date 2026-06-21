from __future__ import annotations

import os
import uuid

from cogito_agent.application import build_runtime_kernel, default_workspace_path
from cogito_agent.models.openai_adapter import OpenAICompatibleAdapter
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def run_e2e_demo(db_path: str = "cogito_demo.db") -> None:
    _load_dotenv()
    print("=" * 56)
    print("  Cogito-Agent E2E Demo")
    print("=" * 56)

    db = Database(db_path)
    db.initialize()
    print(f"\n[DB] Initialized: {db_path}")

    ws_id = str(uuid.uuid4())
    sess_id = str(uuid.uuid4())
    db.connection.execute(
        "INSERT INTO workspaces (id, name) VALUES (?, ?)", (ws_id, "demo-workspace")
    )
    db.connection.execute(
        "INSERT INTO sessions (id, workspace_id, title, status) VALUES (?, ?, ?, ?)",
        (sess_id, ws_id, "E2E Demo Session", "active"),
    )
    db.connection.commit()
    print(f"[Workspace] {ws_id}")
    print(f"[Session]   {sess_id}")

    api_key = os.environ.get("MODEL_API_KEY", "")
    model_name = os.environ.get("MODEL_NAME", "gpt-4o-mini")
    base_url = os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1")

    if api_key:
        adapter = OpenAICompatibleAdapter(api_key=api_key, model=model_name, base_url=base_url)
        print(f"[Model] {model_name} @ {base_url}")
    else:
        adapter = None
        print("[Model] No API key found — using echo mode")

    kernel = build_runtime_kernel(db, model_adapter=adapter, workspace_path=default_workspace_path(ws_id))
    print("[Kernel] Ready\n")

    prompt = "Hello! Please introduce yourself briefly in two sentences."
    print(f"User: {prompt}\n")

    event = RuntimeEvent(
        workspace_id=ws_id,
        session_id=sess_id,
        actor_id="user",
        source=EventSource.cli,
        type=EventType.user_message,
        payload={"text": prompt},
    )

    result = kernel.process(event)

    if result.error:
        print(f"[Error] {result.error}")
    else:
        print(f"Agent: {result.output}")

    cur_t = db.connection.execute("SELECT id, status FROM traces WHERE workspace_id = ?", (ws_id,))
    traces = cur_t.fetchall()
    cur_a = db.connection.execute(
        "SELECT id, action FROM audit_logs WHERE workspace_id = ?", (ws_id,)
    )
    logs = cur_a.fetchall()

    print(f"\n[Trace] {len(traces)} trace(s) recorded")
    print(f"[Audit] {len(logs)} log(s) recorded")

    db.connection.execute(
        "INSERT INTO messages (id, workspace_id, session_id, role, content) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), ws_id, sess_id, "user", prompt),
    )
    db.connection.commit()
    cur = db.connection.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
        (sess_id,),
    )
    msgs = cur.fetchall()
    print(f"[Messages] {len(msgs)} message(s) in session")
    for m in msgs:
        content = str(m["content"])
        if len(content) > 60:
            content = content[:60] + "..."
        print(f"  [{m['role']}] {content}")

    db.close()
    print("\nDone.")


if __name__ == "__main__":
    run_e2e_demo()
