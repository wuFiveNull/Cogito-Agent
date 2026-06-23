from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from cogito_agent.queue.message import InboundMessage, OutboundMessage
from cogito_agent.queue.message_queue import MessageQueue
from cogito_agent.runtime import RuntimeKernel

logger = logging.getLogger(__name__)


class AgentLoop:
    """Background consumer loop: MessageQueue → RuntimeKernel → persistence.

    AgentLoop runs as a long-lived asyncio Task, consuming inbound messages
    from the shared MessageQueue and dispatching them through the
    RuntimeKernel. It is the **single point** where CLI, Web, ACP, and
    other channels converge onto the same kernel instance.

    Startup sequence::

        1. recover_pending() — replay messages that survived a crash
        2. run() — main loop: consume → process → mark_done
    """

    def __init__(
        self,
        kernel: RuntimeKernel,
        queue: MessageQueue,
        *,
        on_outbound: Callable[[OutboundMessage], None] | None = None,
    ) -> None:
        self._kernel = kernel
        self._queue = queue
        self._on_outbound = on_outbound
        self._running = False
        self._handler_registry: dict[str, list[Callable[[OutboundMessage], None]]] = {}

    # ── lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the loop. Recover pending messages first, then consume."""
        if self._running:
            logger.warning("AgentLoop already running")
            return

        self._running = True

        # Recover crash-pending messages
        recovered = await self._queue.enqueue_recovered()
        if recovered:
            logger.info("AgentLoop: recovered %d pending messages", recovered)

        logger.info("AgentLoop started")
        await self._run()

    async def stop(self) -> None:
        """Gracefully stop the loop."""
        self._running = False
        logger.info("AgentLoop stopped")

    # ── main loop ──────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Core consume loop."""
        while self._running:
            try:
                inbound = await asyncio.wait_for(
                    self._queue.consume(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            # Process in a separate task so concurrent messages don't block
            asyncio.create_task(self._process(inbound))

    async def _process(self, inbound: InboundMessage) -> None:
        """Process a single inbound message through the kernel."""
        started = time.monotonic()
        session_id = inbound.session_id
        workspace_id = inbound.workspace_id
        qid = inbound.metadata.get("queue_id", "")

        # Mark as processing (for crash detection)
        self._queue.mark_processing(inbound)

        try:
            # Run through kernel using the queue-aware entry point
            result = await asyncio.to_thread(
                self._kernel.process_from_queue, inbound
            )

            output = result.output or ""
            trace_id = result.trace_id or ""

            # Build outbound message
            outbound = OutboundMessage(
                channel=inbound.channel,
                session_id=session_id,
                workspace_id=workspace_id,
                content=output,
                metadata={
                    "trace_id": trace_id,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "state": result.state.value if hasattr(result.state, "value") else str(result.state),
                },
            )

            # Mark done + resolve any waiting future
            self._queue.mark_done(inbound)
            if qid:
                self._queue.resolve_future(str(qid), outbound)

            # Dispatch outbound to registered handlers
            self._dispatch_outbound(outbound)

        except Exception as exc:
            logger.exception("AgentLoop._process failed: session=%s", session_id)
            self._queue.mark_failed(inbound, str(exc))
            if qid:
                self._queue.fail_future(str(qid), exc)

    # ── outbound dispatch ──────────────────────────────────────────────

    def subscribe(self, channel: str, handler: Callable[[OutboundMessage], None]) -> None:
        """Subscribe a handler to receive outbound messages for a channel."""
        self._handler_registry.setdefault(channel, []).append(handler)

    def _dispatch_outbound(self, msg: OutboundMessage) -> None:
        """Route an outbound message to registered handlers."""
        # Channel-specific handlers
        if self._on_outbound:
            self._on_outbound(msg)
        # Registry-based handlers
        for handler in self._handler_registry.get(msg.channel, []):
            try:
                handler(msg)
            except Exception:
                logger.exception("outbound handler failed for channel=%s", msg.channel)

    # ── properties ─────────────────────────────────────────────────────

    @property
    def kernel(self) -> RuntimeKernel:
        return self._kernel

    @property
    def is_running(self) -> bool:
        return self._running
