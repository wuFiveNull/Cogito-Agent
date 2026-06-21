from cogito_agent.context import ContextEngine


def test_build_empty() -> None:
    engine = ContextEngine()
    items = engine.build([], [], current_message="hello")
    assert len(items) >= 1
    assert items[0].source_type == "current_message"


def test_build_with_messages() -> None:
    engine = ContextEngine()
    messages = [
        {"id": "1", "content": "first message"},
        {"id": "2", "content": "second message"},
    ]
    items = engine.build(messages, [])
    assert any(i.source_type == "message" for i in items)


def test_budget_trim() -> None:
    engine = ContextEngine(total_token_budget=10)
    long_msg = {"id": "1", "content": "word " * 100}
    items = engine.build([long_msg], [])
    total = sum(i.token_estimate for i in items if i.included)
    assert total <= 10


def test_reason_field() -> None:
    engine = ContextEngine()
    items = engine.build([], [], current_message="hi")
    assert items[0].reason == "required"


# ── Dynamic Budget tests ─────────────────────────────────────────────────

from cogito_agent.context.engine import _detect_query_intent, _compute_dynamic_budget_shares


def test_detect_intent_memory_query() -> None:
    assert _detect_query_intent("我记得上次说过什么") == "memory_query"
    assert _detect_query_intent("what did i say about python") == "memory_query"
    assert _detect_query_intent("查一下我之前提到的项目") == "memory_query"


def test_detect_intent_code_task() -> None:
    assert _detect_query_intent("帮我写一个python函数") == "code_task"
    assert _detect_query_intent("implement a sorting algorithm") == "code_task"
    assert _detect_query_intent("def my_function():") == "code_task"


def test_detect_intent_greeting() -> None:
    assert _detect_query_intent("你好") == "greeting"
    assert _detect_query_intent("hello") == "greeting"
    assert _detect_query_intent("Hi") == "greeting"


def test_detect_intent_general() -> None:
    assert _detect_query_intent("今天天气怎么样") == "general"
    assert _detect_query_intent("") == "general"
    assert _detect_query_intent("12345") == "general"


def test_dynamic_budget_memory_query_boosts_retrieval() -> None:
    shares = _compute_dynamic_budget_shares("我记得上次说过什么")
    assert shares["retrieved_memory"] >= 0.25
    assert shares["tool_file_context"] <= 0.10


def test_dynamic_budget_code_task_boosts_tools() -> None:
    shares = _compute_dynamic_budget_shares("帮我写一个python函数")
    assert shares["tool_file_context"] >= 0.25
    assert shares["retrieved_memory"] <= 0.10


def test_dynamic_budget_greeting_minimal() -> None:
    shares = _compute_dynamic_budget_shares("你好")
    assert shares["response_reserve"] >= 0.40
    assert shares["retrieved_memory"] <= 0.10


def test_dynamic_budget_general_default() -> None:
    shares = _compute_dynamic_budget_shares("今天天气怎么样")
    from cogito_agent.context.engine import _DEFAULT_BUDGET_SHARES
    assert shares == _DEFAULT_BUDGET_SHARES
