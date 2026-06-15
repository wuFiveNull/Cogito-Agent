from cogito_agent.storage import Database, MessageRepository, SessionRepository, WorkspaceRepository


def _setup(db: Database) -> str:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    sess_repo = SessionRepository(db)
    sess_repo.create("sess-1", "ws-1", "test")
    return "ws-1"


def test_create_message(db: Database) -> None:
    _setup(db)
    repo = MessageRepository(db)
    msg = repo.create("msg-1", "ws-1", "sess-1", "user", "hello")
    assert msg["role"] == "user"
    assert msg["content"] == "hello"


def test_list_messages_by_session(db: Database) -> None:
    _setup(db)
    repo = MessageRepository(db)
    repo.create("msg-1", "ws-1", "sess-1", "user", "hi")
    repo.create("msg-2", "ws-1", "sess-1", "assistant", "hello")
    msgs = repo.list_by_session("sess-1", "ws-1")
    assert len(msgs) == 2


def test_soft_delete_messages_by_session(db: Database) -> None:
    _setup(db)
    repo = MessageRepository(db)
    repo.create("msg-1", "ws-1", "sess-1", "user", "hi")
    repo.soft_delete_by_session("sess-1", "ws-1")
    assert repo.list_by_session("sess-1", "ws-1") == []
