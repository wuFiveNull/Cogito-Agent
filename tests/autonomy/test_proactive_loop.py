"""Tests for ProactiveLoop."""

from cogito_agent.autonomy import DecisionAction, ProactiveLoop
from cogito_agent.autonomy.events import AutonomyEvent


def test_process_event_push(proactive_loop: ProactiveLoop, wid: str):
    event = AutonomyEvent(title="loop push test", workspace_id=wid)
    decision = proactive_loop.process_event(event)
    assert decision.action == DecisionAction.push
    assert decision.trace_id
    # outbox should have 1 item
    msgs = proactive_loop._outbox.list_all(workspace_id=wid)
    assert len(msgs) == 1


def test_process_event_trace_created(proactive_loop: ProactiveLoop, wid: str):
    event = AutonomyEvent(title="trace test", workspace_id=wid)
    decision = proactive_loop.process_event(event)
    assert decision.trace_id
    # trace should be persisted
    cur = proactive_loop._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM traces WHERE id = ?",
        (decision.trace_id,),
    )
    row = cur.fetchone()
    assert row["cnt"] == 1


def test_process_event_decision_persisted(proactive_loop: ProactiveLoop, wid: str):
    event = AutonomyEvent(title="persist test", workspace_id=wid)
    decision = proactive_loop.process_event(event)
    stored = proactive_loop._decision_store.get_decision(decision.decision_id)
    assert stored is not None
    assert stored["action"] == "push"


def test_process_event_quiet_hours_skip(proactive_loop: ProactiveLoop, wid: str):
    gate = proactive_loop._gate
    gate.set_quiet_hours(wid, start="00:00", end="23:59")
    event = AutonomyEvent(title="quiet skip", workspace_id=wid)
    decision = proactive_loop.process_event(event)
    assert decision.action == DecisionAction.skip
    assert decision.quiet_hours_hit is True


def test_emit_event_push(proactive_loop: ProactiveLoop, wid: str):
    decision = proactive_loop.emit_event(
        title="emit test", body="hello",
        source="cli", workspace_id=wid,
    )
    assert decision.action == DecisionAction.push
    assert decision.event_id


def test_emit_event_trace(proactive_loop: ProactiveLoop, wid: str):
    decision = proactive_loop.emit_event(
        title="emit trace", workspace_id=wid,
        priority="urgent",
    )
    cur = proactive_loop._db.connection.execute(
        "SELECT COUNT(*) AS cnt FROM traces WHERE id = ?",
        (decision.trace_id,),
    )
    assert cur.fetchone()["cnt"] == 1


def test_run_once(proactive_loop: ProactiveLoop):
    result = proactive_loop.run_once()
    assert isinstance(result, list)


def test_load_status(db, proactive_loop: ProactiveLoop):
    state = ProactiveLoop.load_status(proactive_loop._db)
    assert "status" in state


def test_outbox_after_push(proactive_loop: ProactiveLoop, wid: str):
    event = AutonomyEvent(title="outbox check", workspace_id=wid)
    proactive_loop.process_event(event)
    msgs = proactive_loop._outbox.list_all(workspace_id=wid)
    assert len(msgs) >= 1
    assert msgs[0]["title"] == "outbox check"
