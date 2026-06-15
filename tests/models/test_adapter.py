from cogito_agent.models import ModelResponse


def test_model_response_defaults() -> None:
    resp = ModelResponse()
    assert resp.content == ""
    assert resp.tool_intents == []
    assert resp.error is None


def test_model_response_with_data() -> None:
    resp = ModelResponse(
        content="Hello!",
        input_tokens=10,
        output_tokens=5,
        model="gpt-4o-mini",
        provider="openai",
    )
    assert resp.content == "Hello!"
    assert resp.model == "gpt-4o-mini"
