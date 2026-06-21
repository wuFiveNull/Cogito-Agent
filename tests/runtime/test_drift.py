from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cogito_agent.runtime import DriftRuntime
from cogito_agent.runtime.drift import DriftEvent, compute_energy, _next_interval_from_energy
from cogito_agent.shared import EventSource, EventType, RuntimeEvent
from cogito_agent.storage import Database
from cogito_agent.storage.repositories import SessionRepository, WorkspaceRepository


def _setup(db: Database, *, migrate: bool = False) -> None:
    db.initialize()
    if migrate:
        db.migrate()
    ws_repo = WorkspaceRepository(db)
    ws_repo.create("ws-drift", "drift-test")
    sess_repo = SessionRepository(db)
    sess_repo.create("sess-1", "ws-drift", "test")


def test_process_directly() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "direct"},
    )

    drift_event = DriftEvent(event)
    engine._process(drift_event)
    assert drift_event.result is not None
    assert drift_event.result.error is None


def test_submit_via_executor() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "via executor"},
    )

    task_id = engine.submit(event, timeout=5.0)
    assert task_id is not None
    result = engine.get_result(task_id)
    assert result is not None
    assert result.error is None
    assert "via executor" in result.output or result.output == ""

    engine.stop()


def test_submit_with_callback() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    callback_results: list[str] = []

    def _callback(result: object) -> None:
        callback_results.append("called")

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "callback test"},
    )

    task_id = engine.submit(event, callback=_callback, timeout=5.0)
    assert task_id is not None
    assert callback_results == ["called"]

    engine.stop()


def test_list_tasks() -> None:
    db = Database(":memory:")
    _setup(db)
    engine = DriftRuntime(db, max_workers=1)

    event = RuntimeEvent(
        workspace_id="ws-drift",
        session_id="sess-1",
        actor_id="user",
        source=EventSource.api,
        type=EventType.user_message,
        payload={"text": "list test"},
    )

    task_id = engine.submit(event, timeout=5.0)
    assert task_id is not None

    tasks = engine.list_tasks()
    assert len(tasks) >= 1
    matching = [t for t in tasks if t["id"] == task_id]
    assert len(matching) == 1
    assert matching[0]["status"] in ("completed", "failed")

    engine.stop()


def test_get_nonexistent_task() -> None:
    engine = DriftRuntime(Database(":memory:"))
    assert engine.get_result("nonexistent") is None
    assert engine.task_status("nonexistent") is None


def test_maintenance_consolidate_empty() -> None:
    from cogito_agent.runtime.drift import DriftMaintenance

    db = Database(":memory:")
    db.initialize()
    dm = DriftMaintenance(db)
    count = dm.consolidate_memories()
    assert count == 0


def test_maintenance_archive_empty() -> None:
    from cogito_agent.runtime.drift import DriftMaintenance

    db = Database(":memory:")
    db.initialize()
    dm = DriftMaintenance(db)
    count = dm.archive_stale_memories(days=1)
    assert count == 0


def test_maintenance_refresh_fts() -> None:
    from cogito_agent.runtime.drift import DriftMaintenance

    db = Database(":memory:")
    db.initialize()
    dm = DriftMaintenance(db)
    count = dm.refresh_fts()
    assert isinstance(count, int)


def test_maintenance_cleanup_traces_empty() -> None:
    from cogito_agent.runtime.drift import DriftMaintenance

    db = Database(":memory:")
    db.initialize()
    dm = DriftMaintenance(db)
    counts = dm.cleanup_traces(days=1)
    assert counts["traces"] == 0


def test_maintenance_usage_report() -> None:
    from cogito_agent.runtime.drift import DriftMaintenance

    db = Database(":memory:")
    db.initialize()
    dm = DriftMaintenance(db)
    report = dm.usage_report()
    assert isinstance(report, dict)
    assert "messages" in report
    assert "memories" in report
    assert "traces" in report


def test_maintenance_trace_and_audit_logging() -> None:
    from cogito_agent.governance import AuditLogger
    from cogito_agent.runtime.drift import DriftMaintenance
    from cogito_agent.shared import SpanKind
    from cogito_agent.trace import Tracer

    db = Database(":memory:")
    db.initialize()
    dm = DriftMaintenance(db)
    tracer = Tracer(db)
    audit = AuditLogger(db)

    trace = tracer.create_trace("ws_test", "maintenance.test")
    span = tracer.create_span(trace.id, "maintenance.test", SpanKind.runtime)

    count = dm.consolidate_memories("ws_test")
    assert count == 0

    tracer.end_span(span)
    tracer.end_trace(trace)
    audit.log(
        actor_id="maintenance",
        action="maintenance.test",
        resource="database",
        workspace_id="ws_test",
        trace_id=trace.id,
        decision="allow",
        reason="ok",
    )

    # verify trace and audit were persisted
    cur = db.connection.execute("SELECT COUNT(*) FROM traces WHERE id = ?", (trace.id,))
    assert cur.fetchone()[0] > 0
    cur = db.connection.execute("SELECT COUNT(*) FROM audit_logs WHERE trace_id = ?", (trace.id,))
    assert cur.fetchone()[0] > 0


def test_maintenance_policy_allow() -> None:
    from cogito_agent.governance import PolicyEngine
    from cogito_agent.shared import DecisionType, PolicyRequest

    policy = PolicyEngine()
    req = PolicyRequest(
        actor_id="maintenance",
        capability_name="maintenance.usage",
        operation="execute",
        resource="database",
        context="background",
    )
    dec = policy.evaluate(req)
    assert dec.decision == DecisionType.allow_with_audit


def test_maintenance_policy_deny_shell() -> None:
    from cogito_agent.governance import PolicyEngine
    from cogito_agent.shared import DecisionType, PolicyRequest

    policy = PolicyEngine()
    req = PolicyRequest(
        actor_id="maintenance",
        capability_name="shell.execute",
        operation="execute",
        resource="shell",
        context="background",
    )
    dec = policy.evaluate(req)
    assert dec.decision == DecisionType.deny


# ── Energy Model tests ──────────────────────────────────────────────────


def test_compute_energy_no_interaction() -> None:
    """Never interacted → energy = 0.0 (always trigger)."""
    assert compute_energy(None) == 0.0


def test_compute_energy_just_interacted() -> None:
    """Just interacted → energy ≈ 1.0 (very fresh)."""
    now = datetime.now(UTC)
    energy = compute_energy(now, now=now)
    assert energy > 0.99


def test_compute_energy_long_ago() -> None:
    """Days since last interaction → energy near 0."""
    long_ago = datetime.now(UTC) - timedelta(hours=72)
    energy = compute_energy(long_ago)
    assert energy < 0.05


def test_compute_energy_one_hour() -> None:
    """1 hour ago → medium energy (short-term decay has dropped)."""
    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    energy = compute_energy(one_hour_ago)
    assert 0.2 < energy < 0.8


def test_next_interval_high_energy_longer() -> None:
    """High energy → longer interval (less frequent ticks)."""
    high = _next_interval_from_energy(0.9, tick_s1=600, tick_s0=1200, jitter=0)
    low = _next_interval_from_energy(0.1, tick_s1=600, tick_s0=1200, jitter=0)
    assert high == 1200  # low base_score → tick_s0
    assert low == 600    # high base_score → tick_s1


def test_update_last_user_at() -> None:
    """update_last_user_at persists to database and affects energy."""
    from cogito_agent.storage import Database
    db = Database(":memory:")
    _setup(db, migrate=True)
    engine = DriftRuntime(db, max_workers=1)
    engine.stop()

    # Initially no interaction → energy = 0
    assert compute_energy(engine._last_user_at) == 0.0

    # Record interaction
    now = datetime.now(UTC)
    engine.update_last_user_at(now)
    energy = compute_energy(engine._last_user_at, now=now)
    assert energy > 0.99

    # Verify persisted in PresenceStore (new single source of truth)
    row = db.connection.execute(
        "SELECT last_user_at FROM presence WHERE session_key = 'default'"
    ).fetchone()
    assert row is not None, "presence table should have a row"
    assert row["last_user_at"] is not None, "last_user_at should be persisted"
