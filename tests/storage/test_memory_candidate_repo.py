from cogito_agent.storage import Database
from cogito_agent.storage.repositories import MemoryCandidateRepository, WorkspaceRepository


def test_create_candidate(db: Database) -> None:
    repo = MemoryCandidateRepository(db)
    result = repo.create(
        workspace_id="ws-1",
        text="User likes short answers",
        type="preference",
        reason="From conversation",
        confidence=0.8,
    )
    assert result["status"] == "pending"
    assert result["text"] == "User likes short answers"


def test_accept_candidate(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    repo = MemoryCandidateRepository(db)
    c = repo.create(workspace_id="ws-1", text="test fact")
    accepted = repo.accept(c["id"])
    assert accepted["status"] == "accepted"
    cur = db.connection.execute(
        "SELECT * FROM memories WHERE text = ?", ("test fact",)
    )
    assert cur.fetchone() is not None


def test_reject_candidate(db: Database) -> None:
    repo = MemoryCandidateRepository(db)
    c = repo.create(workspace_id="ws-1", text="bad fact")
    rejected = repo.reject(c["id"])
    assert rejected["status"] == "rejected"
    cur = db.connection.execute(
        "SELECT * FROM memories WHERE text = ?", ("bad fact",)
    )
    assert cur.fetchone() is None


def test_list_pending(db: Database) -> None:
    repo = MemoryCandidateRepository(db)
    repo.create(workspace_id="ws-1", text="fact 1")
    repo.create(workspace_id="ws-1", text="fact 2")
    pending = repo.list_pending("ws-1")
    assert len(pending) == 2
