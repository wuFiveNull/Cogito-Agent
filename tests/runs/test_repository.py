from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cogito_agent.runs import RunRepository
from cogito_agent.storage import Database


def _repo() -> tuple[Database, RunRepository]:
    db = Database()
    db.initialize()
    db.migrate()
    return db, RunRepository(db)


def test_run_claim_is_atomic() -> None:
    db, repo = _repo()
    try:
        run = repo.create(run_type="scheduled", workspace_id="workspace")
        run_id = str(run["id"])
        assert repo.claim(run_id, worker_id="worker-a") is True
        assert repo.claim(run_id, worker_id="worker-b") is False
        assert repo.get(run_id)["claimed_by"] == "worker-a"  # type: ignore[index]
    finally:
        db.close()


def test_idempotency_returns_existing_run() -> None:
    db, repo = _repo()
    try:
        first = repo.create(
            run_type="scheduled",
            workspace_id="workspace",
            idempotency_key="job:fire",
        )
        second = repo.create(
            run_type="scheduled",
            workspace_id="workspace",
            idempotency_key="job:fire",
        )
        assert second["id"] == first["id"]
    finally:
        db.close()


def test_expired_lease_is_abandoned() -> None:
    db, repo = _repo()
    try:
        run = repo.create(run_type="scheduled", workspace_id="workspace")
        run_id = str(run["id"])
        assert repo.claim(run_id, worker_id="worker", lease_seconds=1)
        expired = datetime.now(UTC) + timedelta(seconds=2)
        abandoned = repo.abandon_expired(now=expired)
        assert [item["id"] for item in abandoned] == [run_id]
        assert repo.get(run_id)["status"] == "abandoned"  # type: ignore[index]
    finally:
        db.close()


def test_run_payloads_are_redacted() -> None:
    db, repo = _repo()
    try:
        run = repo.create(
            run_type="skill",
            workspace_id="workspace",
            input_data={"api_key": "sk-secret-value"},
        )
        assert "sk-secret-value" not in str(run["input_json"])
    finally:
        db.close()


def test_waiting_approval_resume_cancel_and_retry() -> None:
    db, repo = _repo()
    try:
        run = repo.create(
            run_type="skill",
            workspace_id="workspace",
            max_attempts=2,
        )
        run_id = str(run["id"])
        assert repo.claim(run_id, worker_id="worker")
        assert repo.pause_for_approval(run_id, "approval-1")
        assert repo.get(run_id)["status"] == "waiting_approval"  # type: ignore[index]
        assert repo.resume_waiting(run_id, worker_id="worker")
        assert repo.cancel(run_id, reason="test cancellation")
        assert repo.retry(run_id)
        assert repo.get(run_id)["status"] == "pending"  # type: ignore[index]
    finally:
        db.close()


def test_output_registration_is_idempotent() -> None:
    db, repo = _repo()
    try:
        run = repo.create(run_type="drift", workspace_id="workspace")
        run_id = str(run["id"])
        first = repo.add_output(run_id, "artifact", "artifact-1")
        second = repo.add_output(run_id, "artifact", "artifact-1")
        assert second == first
        assert len(repo.list_outputs(run_id)) == 1
    finally:
        db.close()
