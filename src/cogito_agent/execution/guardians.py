from __future__ import annotations

import ipaddress
import json
import re
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


class PathGuardian:
    """Guard against path traversal and suspicious file paths.

    Uses regex for known patterns + optional LLM for semantic analysis.
    """
    _PATH_KEYS = {"path", "file", "filename", "directory", "destination", "target"}

    def __init__(self, llm_adapter: Any = None) -> None:
        self._llm = llm_adapter

    def set_llm_adapter(self, adapter: Any) -> None:
        self._llm = adapter

    def inspect(
        self,
        request: CapabilityExecutionRequest,
        manifest: CapabilityManifest,
    ) -> str | None:
        del manifest
        for key, value in request.arguments.items():
            if key.lower() not in self._PATH_KEYS or not isinstance(value, str):
                continue
            if "\x00" in value:
                return f"Path argument '{key}' contains a null byte"
            normalized = value.replace("\\", "/")
            if ".." in PurePath(normalized).parts:
                return f"Path traversal detected in '{key}'"

        # LLM secondary check: catch path-like values in non-obvious argument names
        if self._llm:
            suspicious = {
                k: str(v)[:200] for k, v in request.arguments.items()
                if isinstance(v, str) and len(v) > 3
            }
            if suspicious:
                reason = _call_llm_guard(self._llm,
                    f"Capability: {request.capability_name}\n"
                    f"Arguments: {json.dumps(suspicious, ensure_ascii=False)}\n\n"
                    "Does any argument value look like a malicious path (traversal, "
                    "system file overwrite, or unexpected file access)?")
                if reason:
                    return f"LLM path guard: {reason}"
        return None


class ShellGuardian:
    """Guard against destructive shell commands.

    Uses regex for known destructive commands + optional LLM for semantic
    analysis of unknown dangerous patterns.
    """
    _SHELL_NAMES = ("shell", "terminal", "command", "exec", "powershell", "bash")
    _DESTRUCTIVE = re.compile(
        r"(?:^|[;&|]\s*)(?:rm\s+-rf|rmdir\s+/s|del\s+/[sq]|format\s+[a-z]:|"
        r"git\s+reset\s+--hard|shutdown|reboot)(?:\s|$)",
        re.IGNORECASE,
    )

    def __init__(self, llm_adapter: Any = None) -> None:
        self._llm = llm_adapter

    def set_llm_adapter(self, adapter: Any) -> None:
        self._llm = adapter

    def inspect(
        self,
        request: CapabilityExecutionRequest,
        manifest: CapabilityManifest,
    ) -> str | None:
        del manifest
        name = request.capability_name.lower()
        if not any(marker in name for marker in self._SHELL_NAMES):
            return None
        if request.source == "background":
            return "Background execution cannot invoke shell capabilities"
        for value in _strings(request.arguments):
            if self._DESTRUCTIVE.search(value):
                return "Destructive shell command requires a dedicated approved workflow"

        # LLM secondary check: catch destructive commands not in regex
        if self._llm:
            for value in _strings(request.arguments):
                if len(value) > 5:
                    reason = _call_llm_guard(self._llm,
                        f"Capability: {request.capability_name}\n"
                        f"Command: {value[:500]}\n\n"
                        "Does this command look destructive or dangerous "
                        "(data loss, system modification, privilege escalation)?")
                    if reason:
                        return f"LLM shell guard: {reason}"
        return None


class NetworkGuardian:
    """Guard against unsafe network destinations.

    Uses regex for known blocked hosts + optional LLM for semantic analysis
    of suspicious destinations.
    """
    _URL_KEYS = {"url", "uri", "endpoint", "webhook", "base_url"}
    _BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}

    def __init__(self, llm_adapter: Any = None) -> None:
        self._llm = llm_adapter

    def set_llm_adapter(self, adapter: Any) -> None:
        self._llm = adapter

    def inspect(
        self,
        request: CapabilityExecutionRequest,
        manifest: CapabilityManifest,
    ) -> str | None:
        del manifest
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

        # LLM secondary check: catch suspicious URLs not in blocked list
        if self._llm:
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
                        return f"LLM network guard: {reason}"
        return None


class SecretEgressGuardian:
    """Guard against secret/credential leakage via network calls.

    Uses regex for known secret patterns + optional LLM for semantic analysis
    of credential-like values.
    """
    _EGRESS_NAMES = ("http", "network", "webhook", "mcp_", "upload", "send")
    _SECRET = re.compile(
        r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|"
        r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*\S+)",
        re.IGNORECASE,
    )

    def __init__(self, llm_adapter: Any = None) -> None:
        self._llm = llm_adapter

    def set_llm_adapter(self, adapter: Any) -> None:
        self._llm = adapter

    def inspect(
        self,
        request: CapabilityExecutionRequest,
        manifest: CapabilityManifest,
    ) -> str | None:
        del manifest
        name = request.capability_name.lower()
        if not any(marker in name for marker in self._EGRESS_NAMES):
            return None
        if any(self._SECRET.search(value) for value in _strings(request.arguments)):
            return "Potential secret egress detected"

        # LLM secondary check: catch secrets in non-obvious patterns
        if self._llm:
            for value in _strings(request.arguments):
                if len(value) > 10:
                    reason = _call_llm_guard(self._llm,
                        f"Capability: {request.capability_name}\n"
                        f"Value: {value[:300]}\n\n"
                        "Does this value look like an API key, password, token, "
                        "or other secret/credential that should not be sent externally?")
                    if reason:
                        return f"LLM secret guard: {reason}"
        return None


def default_guardians() -> list[Any]:
    return [PathGuardian(), ShellGuardian(), NetworkGuardian(), SecretEgressGuardian()]
