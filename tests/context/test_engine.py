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
