from __future__ import annotations

from cogito_agent.execution import (
    CapabilityExecutionRequest,
    NetworkGuardian,
    PathGuardian,
    SecretEgressGuardian,
    ShellGuardian,
)
from tests.execution.test_executor import _manifest


def _request(
    name: str,
    arguments: dict[str, object],
    source: str = "interactive",
) -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability_name=name,
        arguments=arguments,
        actor_id="assistant",
        source=source,
        workspace_id="workspace",
    )


def test_path_guardian_denies_traversal() -> None:
    finding = PathGuardian().inspect(_request("file.read", {"path": "../secret"}), _manifest())
    assert finding is not None


def test_shell_guardian_denies_background_shell() -> None:
    finding = ShellGuardian().inspect(
        _request("terminal.exec", {"command": "echo ok"}, source="background"),
        _manifest(),
    )
    assert finding is not None


def test_shell_guardian_denies_destructive_command() -> None:
    finding = ShellGuardian().inspect(
        _request("shell.run", {"command": "rm -rf workspace"}),
        _manifest(),
    )
    assert finding is not None


def test_network_guardian_denies_private_ip() -> None:
    finding = NetworkGuardian().inspect(
        _request("http.get", {"url": "http://169.254.169.254/latest"}),
        _manifest(),
    )
    assert finding is not None


def test_secret_egress_guardian_denies_token() -> None:
    finding = SecretEgressGuardian().inspect(
        _request("webhook.send", {"body": "Bearer abcdefghijklmnop"}),
        _manifest(),
    )
    assert finding is not None


# ── LLM Guardian tests ──────────────────────────────────────────────────


class _MockLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def chat(self, messages: list, **kwargs: object) -> object:
        from types import SimpleNamespace
        return SimpleNamespace(content=self.response)


def test_path_guardian_llm_blocks_suspicious() -> None:
    """LLM guard can block path-like values that regex misses."""
    mock = _MockLLM('{"block": true, "reason": "suspicious path to system file"}')
    g = PathGuardian(llm_adapter=mock)
    result = g.inspect(
        _request("file.read", {"path": "/etc/passwd"}),
        _manifest(),
    )
    assert result is not None
    assert "LLM" in result


def test_path_guardian_llm_allows_safe() -> None:
    """LLM guard allows safe paths."""
    mock = _MockLLM('{"block": false, "reason": "looks safe"}')
    g = PathGuardian(llm_adapter=mock)
    result = g.inspect(
        _request("file.read", {"path": "/home/user/documents/report.txt"}),
        _manifest(),
    )
    assert result is None


def test_path_guardian_llm_no_adapter_fallback() -> None:
    """Without LLM adapter, guardian still works via regex only."""
    g = PathGuardian()
    result = g.inspect(
        _request("file.read", {"path": "/etc/passwd"}),
        _manifest(),
    )
    assert result is None


def test_llm_guardian_malformed_response_allows() -> None:
    """Malformed LLM response should fail open (allow) for guardians."""
    mock = _MockLLM("not valid json")
    g = PathGuardian(llm_adapter=mock)
    result = g.inspect(
        _request("file.read", {"path": "/tmp/test.txt"}),
        _manifest(),
    )
    assert result is None


def test_network_guardian_llm_blocks_suspicious() -> None:
    """LLM guard can block network destinations that regex misses."""
    mock = _MockLLM('{"block": true, "reason": "suspicious endpoint"}')
    g = NetworkGuardian(llm_adapter=mock)
    result = g.inspect(
        _request("http.post", {"url": "https://evil.example.com/upload"}),
        _manifest(),
    )
    assert result is not None
    assert "LLM" in result


def test_secret_egress_guardian_llm_blocks_base64() -> None:
    """LLM guard catches base64-encoded secrets that regex may miss."""
    mock = _MockLLM('{"block": true, "reason": "encoded credential"}')
    g = SecretEgressGuardian(llm_adapter=mock)
    result = g.inspect(
        _request("http.post", {"body": "dXNlcm5hbWU6cGFzc3dvcmQ="}),
        _manifest(),
    )
    assert result is not None
    assert "LLM" in result
