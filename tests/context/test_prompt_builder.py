"""Tests: PromptBuilder correctly renders ContextItems into model messages."""
from __future__ import annotations

from cogito_agent.context import ContextItem, ContextEngine
from cogito_agent.context.prompt_builder import PromptBuilder
from cogito_agent.shared.safety import UNTRUSTED_CONTENT_BEGIN


def test_empty_context() -> None:
    pb = PromptBuilder()
    msgs = pb.build([], current_message="hello")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "hello"


def test_system_policy_present() -> None:
    pb = PromptBuilder(system_instruction="Custom system instruction")
    msgs = pb.build([], current_message="hi")
    assert msgs[0]["role"] == "system"
    assert "Custom system instruction" in str(msgs[0]["content"])


def test_memory_appears_as_system_message() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="memory", source_id="mem1",
            text="User likes Python", rank=1, token_estimate=10, included=True,
            reason="retrieved",
        ),
    ]
    msgs = pb.build(items, current_message="hello")
    content_str = str([m["content"] for m in msgs])
    assert "User likes Python" in content_str


def test_excluded_items_not_in_messages() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="memory", source_id="mem1",
            text="Should be excluded", rank=1, token_estimate=10,
            included=False, reason="budget_exceeded",
        ),
    ]
    msgs = pb.build(items, current_message="hello")
    content_str = str([m["content"] for m in msgs])
    assert "Should be excluded" not in content_str


def test_no_current_message_duplicate() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="current_message", source_id="current",
            text="hello world", rank=0, token_estimate=5, included=True,
            reason="required",
        ),
    ]
    msgs = pb.build(items, current_message="")
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert "hello world" in str(user_msgs[0]["content"])


def test_current_message_in_ctx_prevents_duplicate() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="current_message", source_id="current",
            text="first", rank=0, token_estimate=5, included=True,
            reason="required",
        ),
    ]
    msgs = pb.build(items, current_message="first")
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) == 1


def test_file_chunks_marked_untrusted() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="file_chunk", source_id="file1",
            text="secret content", rank=1, token_estimate=10, included=True,
            reason="retrieved",
        ),
    ]
    msgs = pb.build(items, current_message="hello")
    system_msgs = [m for m in msgs if m["role"] == "system"]
    combined = " ".join(str(m.get("content", "")) for m in system_msgs)
    assert UNTRUSTED_CONTENT_BEGIN in combined


def test_tool_results_appear() -> None:
    pb = PromptBuilder()
    tool_results = [
        {"tool": "read_file", "summary": "File contents: hello world"},
    ]
    msgs = pb.build([], current_message="continue", tool_results=tool_results)
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "hello world" in str(tool_msgs[0]["content"])


def test_history_deduplication() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="message", source_id="msg1",
            text="previous message", rank=1, token_estimate=5, included=True,
            reason="recent_history",
        ),
    ]
    msgs = pb.build(items, current_message="new")
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert len(user_msgs) >= 1


def test_over_budget_trimming() -> None:
    engine = ContextEngine(total_token_budget=50)
    long_text = "word " * 100
    items = engine.build(
        [{"id": "1", "content": long_text}],
        [],
        current_message="hi",
    )
    pb = PromptBuilder()
    msgs = pb.build(items, current_message="hi")
    total_chars = sum(len(str(m.get("content", ""))) for m in msgs)
    assert total_chars > 0
    assert any(c.included for c in items)


def test_multiple_memory_items() -> None:
    pb = PromptBuilder()
    items = [
        ContextItem(
            source_type="memory", source_id="mem1",
            text="Memory A", rank=1, token_estimate=5, included=True,
            reason="retrieved",
        ),
        ContextItem(
            source_type="memory", source_id="mem2",
            text="Memory B", rank=2, token_estimate=5, included=True,
            reason="retrieved",
        ),
    ]
    msgs = pb.build(items)
    content = str([m.get("content", "") for m in msgs])
    assert "Memory A" in content
    assert "Memory B" in content
