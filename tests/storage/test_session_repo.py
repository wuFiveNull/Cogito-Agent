from cogito_agent.storage import Database, SessionRepository, WorkspaceRepository


def test_create_session(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    repo = SessionRepository(db)
    sess = repo.create("sess-1", "ws-1", "test-session")
    assert sess["id"] == "sess-1"
    assert sess["workspace_id"] == "ws-1"
    assert sess["title"] == "test-session"


def test_session_workspace_filter(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "a")
    ws_repo.create("ws-2", "b")
    repo = SessionRepository(db)
    repo.create("sess-1", "ws-1")
    repo.create("sess-2", "ws-2")
    ws1_sessions = repo.list_by_workspace("ws-1")
    assert len(ws1_sessions) == 1
    assert ws1_sessions[0]["id"] == "sess-1"


def test_session_cross_workspace_isolation(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "a")
    ws_repo.create("ws-2", "b")
    repo = SessionRepository(db)
    repo.create("sess-1", "ws-1")
    assert repo.get_by_id("sess-1", "ws-2") is None
