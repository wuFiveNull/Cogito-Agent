from __future__ import annotations

from enum import StrEnum

from cogito_agent.trace.redaction import RedactionHelper


class ProviderErrorCode(StrEnum):
    NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    SECRET_MISSING = "PROVIDER_SECRET_MISSING"
    UNREACHABLE = "PROVIDER_UNREACHABLE"
    TIMEOUT = "PROVIDER_TIMEOUT"
    RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    AUTH_FAILED = "PROVIDER_AUTH_FAILED"
    MODEL_UNAVAILABLE = "PROVIDER_MODEL_UNAVAILABLE"
    UNKNOWN_ERROR = "PROVIDER_UNKNOWN_ERROR"


class ProviderError(Exception):
    def __init__(
        self,
        code: ProviderErrorCode,
        message: str = "",
        provider: str = "",
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.provider = provider
        self.retryable = retryable
        safe_msg = safe_provider_error_message(code, provider, message)
        super().__init__(safe_msg)
        self.safe_message = safe_msg

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "message": self.safe_message,
            "retryable": self.retryable,
        }


_redactor = RedactionHelper()


def safe_provider_error_message(
    code: ProviderErrorCode,
    provider: str = "",
    detail: str = "",
) -> str:
    safe_detail = _redactor.redact(detail) if detail else ""
    templates = {
        ProviderErrorCode.NOT_CONFIGURED: (
            f"Provider '{provider}' is not configured"
        ),
        ProviderErrorCode.SECRET_MISSING: (
            f"Provider '{provider}' requires an API key but none found"
        ),
        ProviderErrorCode.UNREACHABLE: (
            f"Provider '{provider}' is unreachable"
        ),
        ProviderErrorCode.TIMEOUT: (
            f"Provider '{provider}' timed out"
        ),
        ProviderErrorCode.RATE_LIMITED: (
            f"Provider '{provider}' rate limited"
        ),
        ProviderErrorCode.AUTH_FAILED: (
            f"Provider '{provider}' authentication failed"
        ),
        ProviderErrorCode.MODEL_UNAVAILABLE: (
            f"Model not available for provider '{provider}'"
        ),
        ProviderErrorCode.UNKNOWN_ERROR: (
            f"Provider '{provider}' error: {safe_detail}" if safe_detail
            else f"Provider '{provider}' unknown error"
        ),
    }
    return templates.get(code, f"Provider error: {safe_detail}")


def normalize_provider_error(
    exc: Exception,
    provider: str = "",
) -> ProviderError:
    msg = str(exc)
    safe_msg_lower = _redactor.redact(msg).lower()

    if "401" in safe_msg_lower or "unauthorized" in safe_msg_lower or "auth" in safe_msg_lower:
        return ProviderError(ProviderErrorCode.AUTH_FAILED, msg, provider)
    if "timeout" in safe_msg_lower or "timed out" in safe_msg_lower:
        return ProviderError(ProviderErrorCode.TIMEOUT, msg, provider, retryable=True)
    if "rate" in safe_msg_lower or "too many" in safe_msg_lower or "429" in safe_msg_lower:
        return ProviderError(ProviderErrorCode.RATE_LIMITED, msg, provider, retryable=True)
    unreachable_keywords = ("unreachable", "connection", "refused")
    if any(k in safe_msg_lower for k in unreachable_keywords):
        return ProviderError(ProviderErrorCode.UNREACHABLE, msg, provider, retryable=True)
    if "model" in safe_msg_lower and "not found" in safe_msg_lower:
        return ProviderError(ProviderErrorCode.MODEL_UNAVAILABLE, msg, provider)
    return ProviderError(ProviderErrorCode.UNKNOWN_ERROR, msg, provider)
