from __future__ import annotations

from cogito_agent.runtime import DriftRuntime, SubagentManager
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository


def _setup(db: Database) -> str:
    db.initialize()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-sub", "subagent-test")
    sess_repo = SessionRepository(db)
    sess_repo.create("parent-sess", "ws-sub", "parent")
    return "ws-sub"


def test_fork_creates_subagent_session() -> None:
    db = Database(":memory:")
    _setup(db)
    mgr = SubagentManager(db)

    sub = mgr.fork(
        parent_session_id="parent-sess",
        workspace_id="ws-sub",
        name="helper",
        instruction="Summarize the conversation.",
    )

    assert sub.id is not None
    assert sub.parent_session_id == "parent-sess"
    assert sub.workspace_id == "ws-sub"
    assert sub.name == "helper"
    assert sub.instruction == "Summarize the conversation."
    assert sub.status == "created"

    sess_repo = SessionRepository(db)
    sess = sess_repo.get_by_id(sub.id, "ws-sub")
    assert sess is not None
    assert "sub:helper" in str(sess.get("title", ""))


def test_fork_with_initial_message() -> None:
    db = Database(":memory:")
    _setup(db)
    mgr = SubagentManager(db)

    sub = mgr.fork(
        parent_session_id="parent-sess",
        workspace_id="ws-sub",
        name="worker",
        instruction="Do the work.",
        initial_message="Start now.",
    )

    from cogito_agent.storage.repositories import MessageRepository

    msg_repo = MessageRepository(db)
    msgs = msg_repo.list_by_session(sub.id, "ws-sub")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_fork_then_run() -> None:
    db = Database(":memory:")
    ws_id = _setup(db)
    drift = DriftRuntime(db, max_workers=1)
    mgr = SubagentManager(db, drift_runtime=drift)

    sub = mgr.fork(
        parent_session_id="parent-sess",
        workspace_id=ws_id,
        name="echo",
        instruction="Echo back whatever you hear.",
    )

    result = mgr.run(sub.id, message="hello subagent", timeout=5.0)
    assert result is not None
    assert sub.status in ("completed", "failed")

    drift.stop()


def test_merge_copies_messages() -> None:
    db = Database(":memory:")
    ws_id = _setup(db)
    drift = DriftRuntime(db, max_workers=1)
    mgr = SubagentManager(db, drift_runtime=drift)

    sub = mgr.fork(
        parent_session_id="parent-sess",
        workspace_id=ws_id,
        name="merger",
    )

    mgr.run(sub.id, message="merge me", timeout=5.0)
    result = mgr.merge(sub.id)
    assert result is not None
    assert sub.status == "merged"

    from cogito_agent.storage.repositories import MessageRepository

    msg_repo = MessageRepository(db)
    parent_msgs = msg_repo.list_by_session("parent-sess", ws_id)
    assert len(parent_msgs) >= 1

    drift.stop()


def test_get_nonexistent_subagent() -> None:
    db = Database(":memory:")
    mgr = SubagentManager(db)
    assert mgr.get("nonexistent") is None
    assert mgr.run("nonexistent") is None
    assert mgr.merge("nonexistent") is None


def test_list_by_parent() -> None:
    db = Database(":memory:")
    _setup(db)
    mgr = SubagentManager(db)

    mgr.fork("parent-sess", "ws-sub", "a")
    mgr.fork("parent-sess", "ws-sub", "b")

    children = mgr.list_by_parent("parent-sess")
    assert len(children) == 2
    assert children[0].name == "a"
    assert children[1].name == "b"
