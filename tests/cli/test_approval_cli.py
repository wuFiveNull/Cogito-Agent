from __future__ import annotations

import os
import tempfile
import uuid

from cogito_agent.shared.skill import (
    OnError,
    SkillManifest,
    SkillRiskLevel,
    SkillStep,
    StepExecutionConfig,
    StepKind,
)
from cogito_agent.skill import SkillRunner
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import ApprovalRepository


def _make_workspace(db: Database, wid: str = "ws-approval-cli") -> str:
    db.connection.execute("INSERT OR IGNORE INTO workspaces (id, name) VALUES (?, ?)", (wid, wid))
    db.connection.commit()
    return wid


def _init_db() -> tuple[Database, str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.unlink(tmp.name)
    db = Database(tmp.name)
    db.initialize()
    db.migrate()
    return db, tmp.name


def _make_approval_skill_manifest() -> SkillManifest:
    return SkillManifest(
        name="test-approval-skill",
        version="1.0.0",
        description="A skill with an approval step",
        risk_level=SkillRiskLevel.medium,
        steps=[
            SkillStep(
                id="step1",
                name="do-something",
                kind=StepKind.transform,
                input_mapping={},
                execution=StepExecutionConfig(timeout_seconds=10),
                on_error=OnError.stop,
            ),
            SkillStep(
                id="step2",
                name="require-approval",
                kind=StepKind.approval,
                input_mapping={},
                execution=StepExecutionConfig(timeout_seconds=10),
                on_error=OnError.stop,
            ),
            SkillStep(
                id="step3",
                name="after-approval",
                kind=StepKind.transform,
                input_mapping={},
                execution=StepExecutionConfig(timeout_seconds=10),
                on_error=OnError.stop,
            ),
        ],
    )


def _make_skill_run_pending(
    db: Database,
    wid: str,
    manifest: SkillManifest,
) -> tuple[str, str]:
    runner = SkillRunner(db)
    result = runner.run(manifest, wid, inputs={})
    assert result.status == "pending_approval"
    assert len(result.step_logs) == 2
    pending_step = result.step_logs[-1]
    assert pending_step["status"] == "pending_approval"
    approval_id = str(pending_step["output"])
    cur = db.connection.execute(
        "SELECT id FROM skill_run_logs WHERE status = 'pending_approval' LIMIT 1"
    )
    row = cur.fetchone()
    assert row is not None
    skill_run_id = str(row["id"])
    return skill_run_id, approval_id


# ── Direct repository tests ────────────────────────────────────────────


def test_approval_create() -> None:
    db, _ = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "test-actor", "test.capability", operation="execute")
    assert approval is not None
    assert approval["status"] == "pending"
    assert approval["workspace_id"] == wid
    assert approval["capability_name"] == "test.capability"
    db.close()


def test_approval_get_by_id_not_found() -> None:
    db, _ = _init_db()
    repo = ApprovalRepository(db)
    assert repo.get_by_id("nonexistent") is None
    db.close()


def test_approval_resolve() -> None:
    db, _ = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "test-actor", "test.capability")
    resolved = repo.resolve(approval["id"], "approved", "cli")
    assert resolved is not None
    assert resolved["status"] == "approved"
    assert resolved["decision"] == "approved"
    assert resolved["decided_by"] == "cli"
    db.close()


def test_approval_resolve_twice_fails() -> None:
    db, _ = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "test-actor", "test.capability")
    resolved = repo.resolve(approval["id"], "approved", "cli")
    assert resolved is not None
    second = repo.resolve(approval["id"], "rejected", "cli")
    assert second is None
    still = repo.get_by_id(approval["id"])
    assert still is not None
    assert still["status"] == "approved"
    db.close()


def test_approval_list_pending() -> None:
    db, _ = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    repo.create(wid, "actor1", "cap.a")
    repo.create(wid, "actor2", "cap.b")
    pending = repo.list_pending(wid)
    assert len(pending) == 2
    db.close()


def test_approval_list_pending_empty() -> None:
    db, _ = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    assert repo.list_pending(wid) == []
    db.close()


def test_approval_list_by_workspace() -> None:
    db, _ = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    a = repo.create(wid, "actor1", "cap.a")
    repo.resolve(a["id"], "approved", "cli")
    repo.create(wid, "actor2", "cap.b")
    all_records = repo.list_by_workspace(wid)
    assert len(all_records) == 2
    db.close()


# ── CLI handler tests (via direct calls, not argparse) ───────────────


def test_run_approval_list_empty() -> None:
    from cogito_agent.cli.approval import _run_approval_list

    db, db_path = _init_db()
    wid = _make_workspace(db)
    db.close()
    ns = _make_ns(db_path=db_path, workspace_id=wid, status="pending")
    _run_approval_list(ns)
    os.unlink(db_path)


def test_run_approval_list_pending() -> None:
    from cogito_agent.cli.approval import _run_approval_list

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    repo.create(wid, "actor1", "cap.a")
    repo.create(wid, "actor2", "cap.b")
    db.close()
    ns = _make_ns(db_path=db_path, workspace_id=wid, status="pending")
    _run_approval_list(ns)
    os.unlink(db_path)


def test_run_approval_list_all() -> None:
    from cogito_agent.cli.approval import _run_approval_list

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    a = repo.create(wid, "actor1", "cap.a")
    repo.resolve(a["id"], "approved", "cli")
    db.close()
    ns = _make_ns(db_path=db_path, workspace_id=wid, status="all")
    _run_approval_list(ns)
    os.unlink(db_path)


def test_run_approval_list_approved() -> None:
    from cogito_agent.cli.approval import _run_approval_list

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    a = repo.create(wid, "actor1", "cap.a")
    repo.resolve(a["id"], "approved", "cli")
    db.close()
    ns = _make_ns(db_path=db_path, workspace_id=wid, status="approved")
    _run_approval_list(ns)
    os.unlink(db_path)


def test_run_approval_show_found() -> None:
    from cogito_agent.cli.approval import _run_approval_show

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval["id"])
    _run_approval_show(ns)
    os.unlink(db_path)


def test_run_approval_show_not_found() -> None:
    from cogito_agent.cli.approval import _run_approval_show

    db, db_path = _init_db()
    db.close()
    ns = _make_ns(db_path=db_path, approval_id="nonexistent")
    _run_approval_show(ns)
    os.unlink(db_path)


def test_run_approval_approve_pending() -> None:
    from cogito_agent.cli.approval import _run_approval_approve

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    approval_id = approval["id"]
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_approve(ns)
    db2 = Database(db_path)
    db2.initialize()
    repo2 = ApprovalRepository(db2)
    resolved = repo2.get_by_id(approval_id)
    assert resolved is not None
    assert resolved["status"] == "approved"
    db2.close()
    os.unlink(db_path)


def test_run_approval_approve_already_resolved() -> None:
    from cogito_agent.cli.approval import _run_approval_approve

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    repo.resolve(approval["id"], "approved", "cli")
    approval_id = approval["id"]
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_approve(ns)
    os.unlink(db_path)


def test_run_approval_approve_nonexistent() -> None:
    from cogito_agent.cli.approval import _run_approval_approve

    db, db_path = _init_db()
    db.close()
    ns = _make_ns(db_path=db_path, approval_id="nonexistent")
    _run_approval_approve(ns)
    os.unlink(db_path)


def test_run_approval_reject_pending() -> None:
    from cogito_agent.cli.approval import _run_approval_reject

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    approval_id = approval["id"]
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_reject(ns)
    db2 = Database(db_path)
    db2.initialize()
    repo2 = ApprovalRepository(db2)
    resolved = repo2.get_by_id(approval_id)
    assert resolved is not None
    assert resolved["status"] == "rejected"
    db2.close()
    os.unlink(db_path)


def test_run_approval_reject_already_resolved() -> None:
    from cogito_agent.cli.approval import _run_approval_reject

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    repo.resolve(approval["id"], "rejected", "cli")
    approval_id = approval["id"]
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_reject(ns)
    os.unlink(db_path)


def test_run_approval_reject_nonexistent() -> None:
    from cogito_agent.cli.approval import _run_approval_reject

    db, db_path = _init_db()
    db.close()
    ns = _make_ns(db_path=db_path, approval_id="nonexistent")
    _run_approval_reject(ns)
    os.unlink(db_path)


# ── Full approve + resume flow ────────────────────────────────────────


def test_approve_and_resume_skill_run() -> None:
    from cogito_agent.cli.approval import _run_approval_approve, _run_approval_resume

    db, db_path = _init_db()
    wid = _make_workspace(db)
    manifest = _make_approval_skill_manifest()
    skill_run_id, approval_id = _make_skill_run_pending(db, wid, manifest)
    db.close()

    ns_approve = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_approve(ns_approve)

    db2 = Database(db_path)
    db2.initialize()
    repo = ApprovalRepository(db2)
    resolved = repo.get_by_id(approval_id)
    assert resolved is not None
    assert resolved["status"] == "approved"
    db2.close()

    ns_resume = _make_ns(db_path=db_path, skill_run_id=skill_run_id)
    _run_approval_resume(ns_resume)

    db3 = Database(db_path)
    db3.initialize()
    # SkillRunner.resume() creates a new row with a new created_at; find the last inserted one
    all_rows = list(
        db3.connection.execute(
            "SELECT rowid, id, status FROM skill_run_logs WHERE skill_name = ? ORDER BY rowid DESC",
            ("test-approval-skill",),
        )
    )
    assert len(all_rows) >= 2, f"Expected at least 2 rows, got {len(all_rows)}"
    # The latest inserted row should be the resumed one (highest rowid)
    latest = all_rows[0]
    assert latest["status"] == "completed", f"Expected completed, got {latest['status']}"
    # Verify original row is preserved
    orig = db3.connection.execute(
        "SELECT status FROM skill_run_logs WHERE id = ?", (skill_run_id,)
    ).fetchone()
    assert orig is not None
    assert orig["status"] == "pending_approval"
    db3.close()
    os.unlink(db_path)


def test_reject_and_resume_skill_run() -> None:
    from cogito_agent.cli.approval import _run_approval_reject, _run_approval_resume

    db, db_path = _init_db()
    wid = _make_workspace(db)
    manifest = _make_approval_skill_manifest()
    skill_run_id, approval_id = _make_skill_run_pending(db, wid, manifest)
    db.close()

    ns_reject = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_reject(ns_reject)

    db2 = Database(db_path)
    db2.initialize()
    repo = ApprovalRepository(db2)
    resolved = repo.get_by_id(approval_id)
    assert resolved is not None
    assert resolved["status"] == "rejected"
    db2.close()

    ns_resume = _make_ns(db_path=db_path, skill_run_id=skill_run_id)
    _run_approval_resume(ns_resume)

    db3 = Database(db_path)
    db3.initialize()
    all_rows = list(
        db3.connection.execute(
            "SELECT rowid, id, status FROM skill_run_logs WHERE skill_name = ? ORDER BY rowid DESC",
            ("test-approval-skill",),
        )
    )
    assert len(all_rows) >= 2, f"Expected at least 2 rows, got {len(all_rows)}"
    latest = all_rows[0]
    assert latest["status"] == "rejected", f"Expected rejected, got {latest['status']}"
    db3.close()
    os.unlink(db_path)


# ── Edge cases ─────────────────────────────────────────────────────────


def test_resume_nonexistent_skill_run() -> None:
    from cogito_agent.cli.approval import _run_approval_resume

    db, db_path = _init_db()
    db.close()
    ns = _make_ns(db_path=db_path, skill_run_id="nonexistent")
    _run_approval_resume(ns)
    os.unlink(db_path)


def test_resume_not_pending_skill_run() -> None:
    """Resume a completed run should fail."""
    from cogito_agent.cli.approval import _run_approval_resume

    db, db_path = _init_db()
    wid = _make_workspace(db)
    manifest = SkillManifest(
        name="simple-skill",
        version="1.0.0",
        steps=[
            SkillStep(id="s1", name="step1", kind=StepKind.transform, input_mapping={}),
        ],
    )
    runner = SkillRunner(db)
    result = runner.run(manifest, wid, inputs={})
    assert result.status == "completed"
    cur = db.connection.execute("SELECT id FROM skill_run_logs WHERE status = 'completed' LIMIT 1")
    row = cur.fetchone()
    assert row is not None
    skill_run_id = str(row["id"])
    db.close()
    ns = _make_ns(db_path=db_path, skill_run_id=skill_run_id)
    _run_approval_resume(ns)
    os.unlink(db_path)


def test_resume_no_resume_data() -> None:
    """Skill run without resume_data_json should fail."""
    from cogito_agent.cli.approval import _run_approval_resume

    db, db_path = _init_db()
    wid = _make_workspace(db)
    rid = str(uuid.uuid4())
    db.connection.execute(
        "INSERT INTO skill_run_logs (id, workspace_id, skill_name, status, resume_data_json)"
        " VALUES (?, ?, ?, 'pending_approval', NULL)",
        (rid, wid, "test-skill"),
    )
    db.connection.commit()
    db.close()
    ns = _make_ns(db_path=db_path, skill_run_id=rid)
    _run_approval_resume(ns)
    os.unlink(db_path)


def test_duplicate_approve_fails() -> None:
    """Approving an already-approved approval should print warning."""
    from cogito_agent.cli.approval import _run_approval_approve

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    repo.resolve(approval["id"], "approved", "cli")
    approval_id = approval["id"]
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_approve(ns)
    db2 = Database(db_path)
    db2.initialize()
    repo2 = ApprovalRepository(db2)
    resolved = repo2.get_by_id(approval_id)
    assert resolved is not None
    assert resolved["status"] == "approved"
    db2.close()
    os.unlink(db_path)


def test_duplicate_reject_fails() -> None:
    """Rejecting an already-rejected approval should print warning."""
    from cogito_agent.cli.approval import _run_approval_reject

    db, db_path = _init_db()
    wid = _make_workspace(db)
    repo = ApprovalRepository(db)
    approval = repo.create(wid, "actor1", "cap.a")
    repo.resolve(approval["id"], "rejected", "cli")
    approval_id = approval["id"]
    db.close()
    ns = _make_ns(db_path=db_path, approval_id=approval_id)
    _run_approval_reject(ns)
    db2 = Database(db_path)
    db2.initialize()
    repo2 = ApprovalRepository(db2)
    resolved = repo2.get_by_id(approval_id)
    assert resolved is not None
    assert resolved["status"] == "rejected"
    db2.close()
    os.unlink(db_path)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_ns(**kwargs: object) -> object:
    class FakeNamespace:
        def __init__(self, **kw: object) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    return FakeNamespace(**kwargs)
