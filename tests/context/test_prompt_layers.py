from __future__ import annotations

from cogito_agent.context import ContextItem, PromptBuilder


def test_stable_layer_hash_ignores_current_message() -> None:
    builder = PromptBuilder()
    first = builder.build_assembly([], current_message="first")
    second = builder.build_assembly([], current_message="second")
    assert first.stable.content_hash == second.stable.content_hash
    assert first.volatile.content_hash != second.volatile.content_hash


def test_context_hash_changes_with_retrieved_memory() -> None:
    builder = PromptBuilder()
    first = builder.build_assembly([], current_message="question")
    second = builder.build_assembly(
        [
            ContextItem(
                source_type="memory_retrieved",
                source_id="memory-1",
                text="Remember this",
            )
        ],
        current_message="question",
    )
    assert first.stable.content_hash == second.stable.content_hash
    assert first.context.content_hash != second.context.content_hash
    assert first.volatile.content_hash == second.volatile.content_hash


def test_all_prompt_layers_report_token_usage() -> None:
    assembly = PromptBuilder().build_assembly([], current_message="hello")
    assert assembly.stable.token_count > 0
    assert assembly.context.token_count > 0
    assert assembly.volatile.token_count > 0
