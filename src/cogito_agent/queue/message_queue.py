from __future__ import annotations

import asyncio
import logging
from typing import Any

from cogito_agent.queue.message import InboundMessage, OutboundMessage
from cogito_agent.storage.database import Database
from cogito_agent.storage.input_queue_repository import InputQueueRepository

logger = logging.getLogger(__name__)


class MessageQueue:
    """Dual-storage message queue: in-memory ``asyncio.Queue`` + SQLite backup.

    Every inbound message is persisted to SQLite *before* being enqueued
    in memory, ensuring crash safety. On startup, ``recover_pending()``
    replays messages that were never processed (or were processing when
    the process died).

    Supports both fire-and-forget (``publish``) and request-response
    (``publish_and_wait``) patterns.  The latter creates an
    ``asyncio.Future`` that AgentLoop resolves when processing completes.
    """

    def __init__(self, db: Database) -> None:
        self._queue: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._repo = InputQueueRepository(db)
        # Futures for request-response bridging (queue_id → Future[OutboundMessage])
        self._pending_futures: dict[str, asyncio.Future[OutboundMessage]] = {}
        # Timeout for how long we wait for a response (5 min default)
        self._response_timeout: float = 300.0

    # ── producer interface ─────────────────────────────────────────────

    async def publish(self, msg: InboundMessage) -> str:
        """Enqueue a message: persist to SQLite first, then put in memory.

        Returns the queue item id for status tracking.
        """
        qid = self._repo.insert(msg, task_type="user_message")
        msg.metadata["queue_id"] = qid
        await self._queue.put(msg)
        logger.debug("MessageQueue.publish: id=%s session=%s", qid, msg.session_id)
        return qid

    async def publish_and_wait(self, msg: InboundMessage) -> OutboundMessage:
        """Enqueue a message and **wait** for the ``OutboundMessage``.

        This is the request-response bridge: the caller (e.g. an HTTP
        endpoint) publishes to the queue and awaits the result that
        AgentLoop produces.  If processing times out or fails, the
        future is cancelled and an exception is raised.
        """
        qid = await self.publish(msg)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[OutboundMessage] = loop.create_future()
        self._pending_futures[qid] = future
        try:
            result = await asyncio.wait_for(future, timeout=self._response_timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_futures.pop(qid, None)
            raise TimeoutError(
                f"MessageQueue: response timeout for {qid}"
            ) from None

    def resolve_future(self, msg_id: str, outbound: OutboundMessage) -> None:
        """Resolve a pending future with the processing result.

        Called by AgentLoop when processing completes.  If no future
        is waiting (fire-and-forget publish), this is a no-op.
        """
        future = self._pending_futures.pop(msg_id, None)
        if future is not None and not future.done():
            future.set_result(outbound)

    def fail_future(self, msg_id: str, error: Exception | str) -> None:
        """Reject a pending future with an error."""
        future = self._pending_futures.pop(msg_id, None)
        if future is not None and not future.done():
            if isinstance(error, Exception):
                future.set_exception(error)
            else:
                future.set_exception(RuntimeError(str(error)))

    # ── consumer interface ─────────────────────────────────────────────

    async def consume(self) -> InboundMessage:
        """Block until a message is available (dequeue from memory)."""
        msg = await self._queue.get()
        return msg

    def mark_processing(self, msg: InboundMessage) -> None:
        """Mark a message as being processed (for crash detection)."""
        qid = msg.metadata.get("queue_id")
        if qid:
            self._repo.update_status(str(qid), "processing")

    def mark_done(self, msg: InboundMessage) -> None:
        """Mark a message as successfully processed."""
        qid = msg.metadata.get("queue_id")
        if qid:
            self._repo.update_status(str(qid), "done")
        self._queue.task_done()

    def mark_failed(self, msg: InboundMessage, error: str = "") -> None:
        """Mark a message as failed (will not be retried automatically)."""
        qid = msg.metadata.get("queue_id")
        if qid:
            self._repo.update_status(str(qid), "failed", error=error)
        self._queue.task_done()

    # ── introspection ──────────────────────────────────────────────────

    @property
    def qsize(self) -> int:
        """Approximate number of messages waiting in memory."""
        return self._queue.qsize()

    def count_by_status(self) -> dict[str, int]:
        """Count queue items by processing status."""
        return self._repo.count_by_status()

    # ── crash recovery ─────────────────────────────────────────────────

    def recover_pending(self) -> list[InboundMessage]:
        """Replay messages that survived a process crash.

        Returns pending messages and processing messages that exceeded
        the timeout (default 5 min), after resetting stale "processing"
        entries back to "pending".

        These should be re-enqueued before starting the main consume loop.
        """
        rows = self._repo.recover_pending()
        recovered = []
        for row in rows:
            msg = InputQueueRepository.row_to_inbound(row)
            recovered.append(msg)
            logger.info(
                "MessageQueue.recover: re-enqueue id=%s session=%s status=%s",
                row.get("id"), row.get("session_id"), row.get("status"),
            )
        return recovered

    async def enqueue_recovered(self) -> int:
        """Re-enqueue recovered messages into the memory queue.

        Returns the number of messages recovered.
        """
        recovered = self.recover_pending()
        for msg in recovered:
            await self._queue.put(msg)
        if recovered:
            logger.info("MessageQueue: enqueued %d recovered messages", len(recovered))
        return len(recovered)
