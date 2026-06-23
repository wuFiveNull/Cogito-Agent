from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import MagicMock, PropertyMock

import pytest

from cogito_agent.queue.message import InboundMessage, OutboundMessage
from cogito_agent.queue.message_queue import MessageQueue
from cogito_agent.storage.input_queue_repository import InputQueueRepository


class FakeDB:
    """In-memory SQLite database for MessageQueue tests."""

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


@pytest.fixture
def queue(db: FakeDB) -> MessageQueue:
    return MessageQueue(db)


@pytest.mark.asyncio
async def test_publish_and_consume(queue: MessageQueue) -> None:
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")
    qid = await queue.publish(msg)
    assert qid is not None

    consumed = await queue.consume()
    assert consumed.channel == "cli"
    assert consumed.content == "hello"
    assert consumed.metadata["queue_id"] == qid


@pytest.mark.asyncio
async def test_publish_and_wait_resolves(queue: MessageQueue, db: FakeDB) -> None:
    msg = InboundMessage(channel="web", session_id="s1", workspace_id="w1", content="ping")

    async def delayed_resolve() -> None:
        await asyncio.sleep(0.01)
        outbound = OutboundMessage(
            channel="web", session_id="s1", workspace_id="w1",
            content="pong", metadata={"trace_id": "t1"},
        )
        # Get the queue_id from the DB after publish
        repo = InputQueueRepository(db)
        rows = repo.list_by_status("pending", limit=1)
        if rows:
            queue.resolve_future(str(rows[0]["id"]), outbound)

    async def do_publish() -> OutboundMessage:
        return await queue.publish_and_wait(msg)

    result = await asyncio.gather(do_publish(), delayed_resolve())
    outbound = result[0]
    assert outbound.content == "pong"
    assert outbound.metadata["trace_id"] == "t1"


@pytest.mark.asyncio
async def test_publish_and_wait_timeout(queue: MessageQueue) -> None:
    """publish_and_wait should raise TimeoutError when no one resolves."""
    queue._response_timeout = 0.05  # short timeout for test
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")
    with pytest.raises(TimeoutError):
        await queue.publish_and_wait(msg)


@pytest.mark.asyncio
async def test_mark_processing_and_done(queue: MessageQueue, db: FakeDB) -> None:
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")
    qid = await queue.publish(msg)

    queue.mark_processing(msg)
    repo = InputQueueRepository(db)
    row = repo.get_by_id(qid)
    assert row is not None
    assert row["status"] == "processing"

    queue.mark_done(msg)
    row = repo.get_by_id(qid)
    assert row["status"] == "done"


@pytest.mark.asyncio
async def test_mark_failed(queue: MessageQueue, db: FakeDB) -> None:
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")
    qid = await queue.publish(msg)
    queue.mark_failed(msg, error="something went wrong")

    repo = InputQueueRepository(db)
    row = repo.get_by_id(qid)
    assert row is not None
    assert row["status"] == "failed"
    assert "something went wrong" in str(row["error"])


@pytest.mark.asyncio
async def test_recover_pending_after_crash(queue: MessageQueue, db: FakeDB) -> None:
    """Simulate crash recovery: messages written to DB before crash are recovered."""
    msg1 = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="msg1")
    msg2 = InboundMessage(channel="cli", session_id="s2", workspace_id="w1", content="msg2")
    await queue.publish(msg1)
    await queue.publish(msg2)

    # Recover should find both pending messages
    recovered = queue.recover_pending()
    assert len(recovered) == 2
    contents = {m.content for m in recovered}
    assert "msg1" in contents
    assert "msg2" in contents


@pytest.mark.asyncio
async def test_recover_stale_processing(queue: MessageQueue, db: FakeDB) -> None:
    """Stale 'processing' entries (started_at too old) should be recovered as pending."""
    import time

    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="stale")
    qid = await queue.publish(msg)

    # Manually set to processing with old timestamp
    long_ago = "2020-01-01 00:00:00"
    db.connection.execute(
        "UPDATE input_queue SET status='processing', started_at=? WHERE id=?",
        (long_ago, qid),
    )
    db.connection.commit()

    recovered = queue.recover_pending()
    assert len(recovered) == 1
    assert recovered[0].content == "stale"


@pytest.mark.asyncio
async def test_fail_future(queue: MessageQueue) -> None:
    """fail_future should raise the error to the publish_and_wait caller."""
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")

    async def do_publish() -> None:
        with pytest.raises(RuntimeError, match="processing failed"):
            await queue.publish_and_wait(msg)

    async def delayed_fail() -> None:
        await asyncio.sleep(0.01)
        # Need to know the queue_id — it's in msg.metadata after publish
        qid = msg.metadata.get("queue_id", "")
        queue.fail_future(str(qid), "processing failed")

    await asyncio.gather(do_publish(), delayed_fail())
