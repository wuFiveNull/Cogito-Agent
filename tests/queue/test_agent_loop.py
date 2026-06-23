from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest

from cogito_agent.queue import AgentLoop, InboundMessage, MessageQueue, OutboundMessage
from cogito_agent.runtime import RuntimeKernel, TurnResult
from cogito_agent.shared import TurnState


class FakeDB:
    """In-memory SQLite for AgentLoop tests."""

    def __init__(self) -> None:
        import sqlite3

        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS input_queue (
                id           TEXT PRIMARY KEY,
                channel      TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                session_id   TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                task_type    TEXT NOT NULL DEFAULT 'user_message',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                started_at   TEXT,
                done_at      TEXT,
                error        TEXT,
                retry_count  INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    @property
    def connection(self) -> Any:
        return self._conn


@pytest.fixture
def db() -> FakeDB:
    return FakeDB()


async def _run_loop_for(loop: AgentLoop, duration: float = 0.2) -> None:
    """Run AgentLoop in a task and stop after ``duration`` seconds."""
    t = asyncio.create_task(loop.start())
    await asyncio.sleep(duration)
    await loop.stop()
    t.cancel()
    try:
        await t
    except (asyncio.CancelledError, StopAsyncIteration):
        pass


@pytest.mark.asyncio
async def test_agent_loop_start_stop(db: FakeDB) -> None:
    """AgentLoop should start and stop cleanly."""
    kernel = MagicMock(spec=RuntimeKernel)
    queue = MessageQueue(db)
    loop = AgentLoop(kernel=kernel, queue=queue)

    assert loop.is_running is False
    await _run_loop_for(loop)
    assert loop.is_running is False


@pytest.mark.asyncio
async def test_agent_loop_processes_message(db: FakeDB) -> None:
    """AgentLoop should consume a message from the queue and process it."""
    kernel = MagicMock(spec=RuntimeKernel)
    kernel.process_from_queue.return_value = TurnResult(
        state=TurnState.completed, output="hello back", trace_id="trace-1"
    )

    queue = MessageQueue(db)
    loop = AgentLoop(kernel=kernel, queue=queue)

    # Publish a message first, then start the loop
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")
    await queue.publish(msg)

    await _run_loop_for(loop)

    # Verify kernel.process_from_queue was called
    assert kernel.process_from_queue.call_count >= 1, "kernel.process_from_queue was not called"

    # Verify the message was marked done
    repo = queue._repo
    counts = repo.count_by_status()
    assert counts.get("done", 0) >= 1, "Message was not marked done"


@pytest.mark.asyncio
async def test_agent_loop_publish_and_wait(db: FakeDB) -> None:
    """AgentLoop should resolve futures from publish_and_wait."""
    kernel = MagicMock(spec=RuntimeKernel)
    kernel.process_from_queue.return_value = TurnResult(
        state=TurnState.completed, output="pong", trace_id="trace-1"
    )

    queue = MessageQueue(db)
    loop = AgentLoop(kernel=kernel, queue=queue)

    # Start loop
    loop_task = asyncio.create_task(loop.start())
    await asyncio.sleep(0.05)

    # publish_and_wait
    msg = InboundMessage(channel="web", session_id="s1", workspace_id="w1", content="ping")
    outbound = await queue.publish_and_wait(msg)

    assert outbound.content == "pong"
    assert outbound.session_id == "s1"

    await loop.stop()
    loop_task.cancel()
    try:
        await loop_task
    except (asyncio.CancelledError, StopAsyncIteration):
        pass


@pytest.mark.asyncio
async def test_agent_loop_handles_error(db: FakeDB) -> None:
    """AgentLoop should mark message as failed when kernel raises."""
    kernel = MagicMock(spec=RuntimeKernel)
    kernel.process_from_queue.side_effect = ValueError("kernel error")

    queue = MessageQueue(db)
    loop = AgentLoop(kernel=kernel, queue=queue)

    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="fail")
    await queue.publish(msg)

    await _run_loop_for(loop)

    counts = queue._repo.count_by_status()
    assert counts.get("failed", 0) >= 1, "Message was not marked failed"


@pytest.mark.asyncio
async def test_inbound_to_runtime_event_conversion() -> None:
    """Test that RuntimeKernel._inbound_to_event produces correct RuntimeEvent."""
    from cogito_agent.runtime.kernel import RuntimeKernel as RK

    msg = InboundMessage(
        channel="cli",
        session_id="s1",
        workspace_id="w1",
        content="hello world",
    )
    event = RK._inbound_to_event(msg)
    assert event.workspace_id == "w1"
    assert event.session_id == "s1"
    assert event.payload["text"] == "hello world"

    msg_web = InboundMessage(
        channel="web",
        session_id="s2",
        workspace_id="w2",
        content="",
        media=[{"type": "image", "uri": "data:img"}],
        metadata={"actor_id": "bot"},
    )
    event2 = RK._inbound_to_event(msg_web)
    assert event2.workspace_id == "w2"
    assert event2.payload.get("content") is not None
    media = event2.payload["content"]
    assert isinstance(media, list)
    assert media[0]["type"] == "image"
