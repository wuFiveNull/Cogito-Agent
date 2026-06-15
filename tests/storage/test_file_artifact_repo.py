from cogito_agent.storage import Database, FileArtifactRepository, WorkspaceRepository


def test_create_file_artifact(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "test")
    repo = FileArtifactRepository(db)
    art = repo.create("f-1", "ws-1", "/tmp/test.txt", "text/plain", "abc123")
    assert art["path"] == "/tmp/test.txt"
    assert art["sha256"] == "abc123"


def test_file_artifact_workspace_isolation(db: Database) -> None:
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-1", "a")
    ws_repo.create("ws-2", "b")
    repo = FileArtifactRepository(db)
    repo.create("f-1", "ws-1", "/tmp/a.txt")
    assert repo.get_by_id("f-1", "ws-2") is None
