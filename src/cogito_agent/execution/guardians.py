from __future__ import annotations

import ipaddress
import json
import re
from abc import ABC, abstractmethod
from pathlib import PurePath
from typing import Any
from urllib.parse import urlparse

from cogito_agent.shared import CapabilityManifest

from .models import CapabilityExecutionRequest


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_strings(item))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_strings(item))
        return result
    return []


def _call_llm_guard(adapter: Any, prompt: str) -> str | None:
    """Call the LLM guard and return a block reason, or None if safe."""
    if not adapter:
        return None
    try:
        resp = adapter.chat([
            {"role": "system", "content": (
                "你是安全检测代理。判断用户的请求是否包含安全风险。"
                "只返回JSON：{\"block\": true/false, \"reason\": \"...\"}"
            )},
            {"role": "user", "content": prompt},
        ])
        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0]
        result = json.loads(raw)
        if result.get("block"):
            return str(result.get("reason", "LLM guard blocked"))
    except Exception:
        pass
    return None


class Guardian(ABC):
    """Base class for capability execution guardians.

    Provides the ``inspect`` template method that runs deterministic
    hard rules first and, only if those pass, an optional LLM-based
    semantic fallback.

    Subclasses must set ``_tag`` (used in block reason messages) and
    implement ``_hard_rules`` + ``_llm_checks``.
    """
    _tag: str = ""

    def __init__(self, llm_adapter: Any = None) -> None:
        self._llm = llm_adapter

    def set_llm_adapter(self, adapter: Any) -> None:
        self._llm = adapter

    @abstractmethod
    def _hard_rules(self, request: CapabilityExecutionRequest) -> str | None:
        """Deterministic checks. Return a block reason or None."""

    @abstractmethod
    def _llm_checks(self, request: CapabilityExecutionRequest) -> str | None:
        """Semantic LLM checks. Only called when ``self._llm`` is set.
        Return a raw block reason (without tag prefix) or None.
        """

    def inspect(
        self,
        request: CapabilityExecutionRequest,
        manifest: CapabilityManifest,
    ) -> str | None:
        del manifest
        reason = self._hard_rules(request)
        if reason:
            return reason
        if self._llm:
            reason = self._llm_checks(request)
            if reason:
                return f"LLM {self._tag} guard: {reason}"
        return None


class PathGuardian(Guardian):
    """Guard against path traversal and suspicious file paths.

    Uses regex for known patterns + optional LLM for semantic analysis.
    """
    _tag = "path"
    _PATH_KEYS = {"path", "file", "filename", "directory", "destination", "target"}

    def _hard_rules(self, request: CapabilityExecutionRequest) -> str | None:
        for key, value in request.arguments.items():
            if key.lower() not in self._PATH_KEYS or not isinstance(value, str):
                continue
            if "\x00" in value:
                return f"Path argument '{key}' contains a null byte"
            normalized = value.replace("\\", "/")
            if ".." in PurePath(normalized).parts:
                return f"Path traversal detected in '{key}'"
        return None

    def _llm_checks(self, request: CapabilityExecutionRequest) -> str | None:
        suspicious = {
            k: str(v)[:200] for k, v in request.arguments.items()
            if isinstance(v, str) and len(v) > 3
        }
        if not suspicious:
            return None
        return _call_llm_guard(self._llm,
            f"Capability: {request.capability_name}\n"
            f"Arguments: {json.dumps(suspicious, ensure_ascii=False)}\n\n"
            "Does any argument value look like a malicious path (traversal, "
            "system file overwrite, or unexpected file access)?")


class ShellGuardian(Guardian):
    """Guard against destructive shell commands, banned tools, and network writes.

    Uses regex for known destructive commands + optional LLM for semantic
    analysis of unknown dangerous patterns.
    """
    _tag = "shell"
    _SHELL_NAMES = ("shell", "terminal", "command", "exec", "powershell", "bash")

    # Commands that should never be run through an agent shell
    _BANNED_CMDS: set[str] = {
        "nc", "ncat", "netcat", "telnet", "ssh", "sftp",
        "lynx", "w3m", "links", "elinks",
        "firefox", "chrome", "chromium", "brave", "opera",
    }

    # Network commands that can write remote content to disk
    _NETWORK_CMDS: set[str] = {"curl", "wget", "httpie", "xh", "aria2c"}
    _NETWORK_WRITE_FLAGS: set[str] = {"-o", "-O", "--output", "--download"}

    _DESTRUCTIVE = re.compile(
        r"(?:^|[;&|]\s*)(?:rm\s+-rf|rmdir\s+/s|del\s+/[sq]|format\s+[a-z]:|"
        r"git\s+reset\s+--hard|shutdown|reboot)(?:\s|$)",
        re.IGNORECASE,
    )

    def _hard_rules(self, request: CapabilityExecutionRequest) -> str | None:
        name = request.capability_name.lower()
        if not any(marker in name for marker in self._SHELL_NAMES):
            return None
        if request.source == "background":
            return "Background execution cannot invoke shell capabilities"

        for value in _strings(request.arguments):
            # Tokenize the command string for finer-grained checks
            tokens = value.split()

            # Block banned interactive/network tools
            first_word = tokens[0].lower() if tokens else ""
            if first_word in self._BANNED_CMDS:
                return (
                    f"Banned command '{first_word}' is not allowed in agent shell"
                )

            # Block network tools writing to disk
            if first_word in self._NETWORK_CMDS:
                for token in tokens[1:]:
                    # Check for short flags containing o/O/C (write output)
                    if re.match(r"^-[a-zA-Z]*[oOC]", token) or token in self._NETWORK_WRITE_FLAGS:
                        return (
                            "Network command with write flag is blocked. "
                            "Download remote content with an approved workflow."
                        )

            # Block destructive system commands
            if self._DESTRUCTIVE.search(value):
                return "Destructive shell command requires a dedicated approved workflow"
        return None

    def _llm_checks(self, request: CapabilityExecutionRequest) -> str | None:
        for value in _strings(request.arguments):
            if len(value) > 5:
                reason = _call_llm_guard(self._llm,
                    f"Capability: {request.capability_name}\n"
                    f"Command: {value[:500]}\n\n"
                    "Does this command look destructive or dangerous "
                    "(data loss, system modification, privilege escalation)?")
                if reason:
                    return reason
        return None


class NetworkGuardian(Guardian):
    """Guard against unsafe network destinations.

    Uses regex for known blocked hosts + optional LLM for semantic analysis
    of suspicious destinations.
    """
    _tag = "network"
    _URL_KEYS = {"url", "uri", "endpoint", "webhook", "base_url"}
    _BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}

    def _hard_rules(self, request: CapabilityExecutionRequest) -> str | None:
        for key, value in request.arguments.items():
            if key.lower() not in self._URL_KEYS or not isinstance(value, str):
                continue
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower().rstrip(".")
            if host in self._BLOCKED_HOSTS:
                return f"Blocked local or metadata endpoint in '{key}'"
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                continue
            if (
                address.is_loopback
                or address.is_private
                or address.is_link_local
                or address.is_reserved
                or address.is_unspecified
            ):
                return f"Blocked non-public network address in '{key}'"
        return None

    def _llm_checks(self, request: CapabilityExecutionRequest) -> str | None:
        for key, value in request.arguments.items():
            if key.lower() in self._URL_KEYS and isinstance(value, str) and len(value) > 5:
                reason = _call_llm_guard(self._llm,
                    f"Capability: {request.capability_name}\n"
                    f"URL/key: {key}\n"
                    f"Value: {value[:300]}\n\n"
                    "Does this URL/endpoint look unsafe (known malicious, "
                    "phishing, internal service that shouldn't be called, "
                    "or data exfiltration destination)?")
                if reason:
                    return reason
        return None


class SecretEgressGuardian(Guardian):
    """Guard against secret/credential leakage via network calls.

    Uses regex for known secret patterns + optional LLM for semantic analysis
    of credential-like values.
    """
    _tag = "secret"
    _EGRESS_NAMES = ("http", "network", "webhook", "mcp_", "upload", "send")
    _SECRET = re.compile(
        r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
        r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*\S+)",
        re.IGNORECASE,
    )

    def _hard_rules(self, request: CapabilityExecutionRequest) -> str | None:
        name = request.capability_name.lower()
        if not any(marker in name for marker in self._EGRESS_NAMES):
            return None
        if any(self._SECRET.search(value) for value in _strings(request.arguments)):
            return "Potential secret egress detected"
        return None

    def _llm_checks(self, request: CapabilityExecutionRequest) -> str | None:
        for value in _strings(request.arguments):
            if len(value) > 10:
                reason = _call_llm_guard(self._llm,
                    f"Capability: {request.capability_name}\n"
                    f"Value: {value[:300]}\n\n"
                    "Does this value look like an API key, password, token, "
                    "or other secret/credential that should not be sent externally?")
                if reason:
                    return reason
        return None


def default_guardians() -> list[Any]:
    return [PathGuardian(), ShellGuardian(), NetworkGuardian(), SecretEgressGuardian()]
