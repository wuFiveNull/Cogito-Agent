from cogito_agent.governance import PolicyEngine
from cogito_agent.shared import DecisionType, PolicyRequest


def test_allow_user_read() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="user",
        capability_name="local.file_read",
        resource="workspace_file",
        operation="read",
        context="interactive",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.allow_with_audit


def test_deny_assistant_delete() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="assistant",
        capability_name="local.file_delete",
        resource="workspace_file",
        operation="delete",
        context="interactive",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny


def test_require_approval_assistant_write() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="assistant",
        capability_name="local.file_write",
        resource="workspace_file",
        operation="write",
        context="interactive",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.require_approval


def test_deny_skill_background_network() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="skill",
        capability_name="network.http_get",
        resource="network",
        operation="call",
        context="background",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny


def test_unknown_matches_catchall() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="unknown",
        capability_name="unknown.tool",
        resource="unknown",
        operation="unknown",
        context="unknown",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny


def test_background_deny_delete() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="local.file_delete",
        resource="*",
        operation="delete",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_deny_file_write() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="skill",
        capability_name="local.file_write",
        resource="workspace_file",
        operation="write",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_deny_secret_read() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="secret.get",
        resource="secret",
        operation="read",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_deny_shell_execute() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="local.shell",
        resource="shell",
        operation="execute",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.deny


def test_background_allow_file_read() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="local.file_read",
        resource="workspace_file",
        operation="read",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.allow_with_audit


def test_background_allow_model_call() -> None:
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="background_agent",
        capability_name="model.invoke",
        resource="model",
        operation="call_model",
        context="background",
    )
    assert engine.evaluate(req).decision == DecisionType.allow_with_audit


def test_custom_rules() -> None:
    from cogito_agent.governance.policy import PolicyRule

    engine = PolicyEngine(
        rules=[
            PolicyRule("*", "read", "*", DecisionType.allow),
            PolicyRule("*", "*", "*", DecisionType.escalate),
        ]
    )
    req = PolicyRequest(
        actor_id="test",
        capability_name="any",
        resource="any",
        operation="read",
        context="any",
    )
    assert engine.evaluate(req).decision == DecisionType.allow


# ── LLM Fallback tests ──────────────────────────────────────────────────


class _MockLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def chat(self, messages: list, **kwargs: object) -> object:
        from types import SimpleNamespace
        return SimpleNamespace(content=self.response)


def test_llm_fallback_allows_when_missing_rule() -> None:
    """When no rule matches AND no final escalate, LLM can allow."""
    mock = _MockLLM('{"decision": "allow", "reason": "safe operation"}')
    engine = PolicyEngine(llm_adapter=mock)
    req = PolicyRequest(
        actor_id="unknown_actor",
        capability_name="unknown_capability",
        resource="unknown",
        operation="unknown",
        context="unknown",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.allow_with_audit
    assert "LLM fallback" in decision.reason


def test_llm_fallback_denies_when_missing_rule() -> None:
    """LLM can also deny (custom rules without catch-all)."""
    mock = _MockLLM('{"decision": "deny", "reason": "too risky"}')
    from cogito_agent.governance import PolicyRule
    engine = PolicyEngine(rules=[
        PolicyRule("user", "read", "interactive", DecisionType.allow),
    ], llm_adapter=mock)
    req = PolicyRequest(
        actor_id="unknown",
        capability_name="unknown",
        resource="unknown",
        operation="delete",
        context="background",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny
    assert "LLM fallback" in decision.reason


def test_llm_fallback_no_adapter_denies() -> None:
    """Without LLM adapter, unhandled rules deny."""
    engine = PolicyEngine()
    req = PolicyRequest(
        actor_id="completely_unknown",
        capability_name="something_new",
        resource="something",
        operation="something",
        context="edge_case",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny
    assert "no LLM fallback" in decision.reason


def test_llm_fallback_malformed_response_denies() -> None:
    """Malformed LLM response should fail closed (deny)."""
    mock = _MockLLM("not valid json at all")
    engine = PolicyEngine(llm_adapter=mock)
    req = PolicyRequest(
        actor_id="x", capability_name="y", resource="z", operation="w", context="v",
    )
    decision = engine.evaluate(req)
    assert decision.decision == DecisionType.deny
