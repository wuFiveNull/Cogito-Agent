from __future__ import annotations

from cogito_agent.queue.message import InboundMessage, OutboundMessage


def test_inbound_message_defaults() -> None:
    """InboundMessage should have sensible defaults for optional fields."""
    msg = InboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="hello")
    assert msg.channel == "cli"
    assert msg.session_id == "s1"
    assert msg.workspace_id == "w1"
    assert msg.content == "hello"
    assert msg.media is None
    assert msg.metadata == {}


def test_inbound_message_with_media() -> None:
    msg = InboundMessage(
        channel="web",
        session_id="s1",
        workspace_id="w1",
        content="",
        media=[{"type": "image", "uri": "data:image/png;base64,abc"}],
        metadata={"actor_id": "user", "request_id": "req-123"},
    )
    assert msg.media is not None
    assert len(msg.media) == 1
    assert msg.media[0]["type"] == "image"
    assert msg.metadata["actor_id"] == "user"


def test_outbound_message_defaults() -> None:
    msg = OutboundMessage(channel="cli", session_id="s1", workspace_id="w1", content="reply")
    assert msg.channel == "cli"
    assert msg.content == "reply"
    assert msg.thinking is None
    assert msg.metadata == {}


def test_outbound_message_with_thinking() -> None:
    msg = OutboundMessage(
        channel="web",
        session_id="s1",
        workspace_id="w1",
        content="reply",
        thinking="reasoning...",
        metadata={"trace_id": "trace-xyz", "latency_ms": 1500},
    )
    assert msg.thinking == "reasoning..."
    assert msg.metadata["trace_id"] == "trace-xyz"
    assert msg.metadata["latency_ms"] == 1500
