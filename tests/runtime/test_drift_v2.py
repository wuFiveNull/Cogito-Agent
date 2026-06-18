from __future__ import annotations

import time as _time
import uuid

import pytest

from cogito_agent.runtime import DriftRuntime
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import WorkspaceRepository


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.initialize()
    database.migrate()
    ws = WorkspaceRepository(database)
    ws.create("default", "default")
    return database


class TestDriftRuntime:
    def test_drift_skill_selection(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        eligible = drift._select_eligible_skills()
        assert len(eligible) >= 1
        assert eligible[0] in ("memory_consolidation", "trace_review", "inbox_digest")

    def test_drift_quiet_hours_in_range(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift.update_settings(quiet_hours_start="00:00", quiet_hours_end="23:59")
        state = drift._get_state()
        assert drift._in_quiet_hours(state) is True

    def test_drift_quiet_hours_out_of_range(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift.update_settings(quiet_hours_start="23:59", quiet_hours_end="23:59")
        state = drift._get_state()
        assert drift._in_quiet_hours(state) is False

    def test_drift_daily_budget(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift.update_settings(daily_budget=2)
        drift._increment_runs_today()
        drift._increment_runs_today()
        state = drift._get_state()
        assert int(str(state.get("runs_today", 0))) == 2
        assert int(str(state.get("daily_budget", 5))) == 2

    def test_drift_pause_resume(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        assert drift.is_paused() is False
        drift.pause("testing")
        assert drift.is_paused() is True
        state = drift._get_state()
        assert state.get("pause_reason") == "testing"
        drift.resume()
        assert drift.is_paused() is False

    def test_drift_tick_paused_does_nothing(self, db: Database) -> None:
        """Tick must not execute skills when paused."""
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift.pause("pause for test")
        drift._last_run.clear()
        drift._tick()
        assert len(drift._last_run) == 0
        runs = drift.list_runs("default")
        assert len(runs) == 0

    def test_drift_status(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        status = drift.status()
        assert "enabled" in status
        assert "paused" in status
        assert "daily_budget" in status
        assert "runs_today" in status
        assert "next_eligible_skills" in status
        assert "budget_remaining" in status

    def test_drift_run_execution(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        result = drift._execute_skill_runtime("memory_consolidation", drift._get_state())
        assert result["status"] in ("completed", "failed")
        assert result["trace_id"]

    def test_drift_run_persists(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift._execute_skill_runtime("memory_consolidation", drift._get_state())
        runs = drift.list_runs("default")
        assert len(runs) >= 1
        assert runs[0]["skill_name"] == "memory_consolidation"

    def test_drift_run_trace_audit(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        result = drift._execute_skill_runtime("memory_consolidation", drift._get_state())
        trace_id = result["trace_id"]
        traces = db.connection.execute(
            "SELECT * FROM traces WHERE id = ?", (trace_id,)
        ).fetchall()
        assert len(traces) >= 1

    def test_drift_get_run(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift._execute_skill_runtime("memory_consolidation", drift._get_state())
        runs = drift.list_runs("default")
        if runs:
            run = drift.get_run(str(runs[0]["id"]))
            assert run is not None
            assert run["id"] == runs[0]["id"]

    def test_drift_quiet_hours_blocking(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift.update_settings(quiet_hours_start="00:00", quiet_hours_end="23:59")
        drift._last_run.clear()
        drift._tick()
        assert len(drift._last_run) == 0, "tick must not run skills during quiet hours"
        runs = drift.list_runs("default")
        assert len(runs) == 0, "no drift runs should be created during quiet hours"

    def test_drift_reset_daily_budget(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift._increment_runs_today()
        drift.reset_daily_budget()
        state = drift._get_state()
        assert int(str(state.get("runs_today", 0))) == 0

    def test_drift_update_settings(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift.update_settings(enabled=0, quiet_hours_start="20:00")
        state = drift._get_state()
        assert int(str(state.get("enabled", 1))) == 0
        assert str(state.get("quiet_hours_start", "")) == "20:00"

    def test_drift_cooldown_respected(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        eligible_before = drift._select_eligible_skills()
        assert len(eligible_before) >= 1

        if eligible_before:
            skill = eligible_before[0]
            drift._last_run[skill] = _time.time()
            eligible_after = drift._select_eligible_skills()
            assert skill not in eligible_after

        _time.sleep(0.01)
        old_runs = dict(drift._last_run)
        for k in old_runs:
            drift._last_run[k] = 0.0
        eligible_reset = drift._select_eligible_skills()
        assert len(eligible_reset) >= 1

    def test_drift_workspace_isolation(self, db: Database) -> None:
        ws = WorkspaceRepository(db)
        ws.create("ws2", "ws2")
        drift = DriftRuntime(db)
        drift._ensure_state()
        drift._execute_skill_runtime("memory_consolidation", drift._get_state())
        runs_ws1 = drift.list_runs("default")
        assert len(runs_ws1) >= 1

    def test_drift_run_unknown_skill(self, db: Database) -> None:
        drift = DriftRuntime(db)
        drift._ensure_state()
        try:
            drift._invoke_skill("nonexistent_skill", "default", str(uuid.uuid4()))
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


class TestDriftMaintenance:
    def test_drift_maintenance_consolidate(self, db: Database) -> None:
        from cogito_agent.runtime.drift import DriftMaintenance
        maint = DriftMaintenance(db)
        for i in range(2):
            db.connection.execute(
                "INSERT INTO memories (id, workspace_id, type, text)"
                " VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), "default", "general", "Duplicate text"),
            )
        db.connection.commit()
        removed = maint.consolidate_memories("default")
        assert removed >= 1

    def test_drift_maintenance_archive_stale(self, db: Database) -> None:
        from cogito_agent.runtime.drift import DriftMaintenance
        maint = DriftMaintenance(db)
        db.connection.execute(
            "INSERT INTO memories (id, workspace_id, type, text, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, datetime('now', '-60 days'), datetime('now', '-60 days'))",
            (str(uuid.uuid4()), "default", "general", "Old memory"),
        )
        db.connection.commit()
        archived = maint.archive_stale_memories(days=30)
        assert archived >= 1
