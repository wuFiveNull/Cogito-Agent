from cogito_agent.storage import Database, WorkspaceRepository


def test_create_workspace(db: Database) -> None:
    repo = WorkspaceRepository(db)
    ws = repo.create("ws-1", "test-workspace")
    assert ws["id"] == "ws-1"
    assert ws["name"] == "test-workspace"


def test_get_workspace_not_found(db: Database) -> None:
    repo = WorkspaceRepository(db)
    assert repo.get_by_id("non-existent") is None


def test_soft_delete_workspace(db: Database) -> None:
    repo = WorkspaceRepository(db)
    repo.create("ws-1", "test-workspace")
    repo.soft_delete("ws-1")
    assert repo.get_by_id("ws-1") is None


def test_list_workspaces_excludes_deleted(db: Database) -> None:
    repo = WorkspaceRepository(db)
    repo.create("ws-1", "active")
    repo.create("ws-2", "to-delete")
    repo.soft_delete("ws-2")
    all_ws = repo.list_all()
    assert len(all_ws) == 1
    assert all_ws[0]["id"] == "ws-1"
