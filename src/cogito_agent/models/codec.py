from __future__ import annotations

from typing import Protocol, runtime_checkable

from cogito_agent.models.messages import ChatMessage, FilePart, ImagePart, TextPart
from cogito_agent.models.provider_errors import ProviderError, ProviderErrorCode


class UnsupportedModalityError(ProviderError):
    def __init__(
        self,
        modality: str,
        provider: str = "",
        message: str = "",
    ) -> None:
        detail = message or f"Provider '{provider}' does not support modality '{modality}'"
        super().__init__(
            ProviderErrorCode.UNSUPPORTED_MODALITY,
            message=detail,
            provider=provider,
            retryable=False,
        )
        self.modality = modality


@runtime_checkable
class ProviderMessageCodec(Protocol):
    def validate_request(self, messages: list[ChatMessage], **kwargs: object) -> None:
        ...

    def encode_messages(
        self, messages: list[ChatMessage], **kwargs: object
    ) -> list[dict[str, object]]:
        ...

    def encode(self, message: ChatMessage) -> dict[str, object]:
        ...


class TextOnlyCodec:
    """Codec for text-only models (e.g., DeepSeek text model).

    Raises UnsupportedModalityError if any message contains non-text content.
    """

    def __init__(self, provider: str = "unknown") -> None:
        self._provider = provider

    def validate_request(self, messages: list[ChatMessage], **kwargs: object) -> None:
        for msg in messages:
            for part in msg.content:
                if not isinstance(part, TextPart):
                    raise UnsupportedModalityError(
                        modality=part.type,
                        provider=self._provider,
                        message=f"Provider '{self._provider}' only supports text, "
                                f"but received '{part.type}' content",
                    )

    def encode_messages(
        self, messages: list[ChatMessage], **kwargs: object
    ) -> list[dict[str, object]]:
        self.validate_request(messages)
        return [self.encode(m) for m in messages]

    def encode(self, message: ChatMessage) -> dict[str, object]:
        d: dict[str, object] = {"role": message.role.value}
        text = message.get_text()
        if text:
            d["content"] = text
        else:
            d["content"] = ""
        if message.tool_call_id:
            d["tool_call_id"] = message.tool_call_id
        if message.name:
            d["name"] = message.name
        return d


class OpenAICompatibleCodec:
    """Codec for OpenAI-compatible multimodal models.

    Encodes TextPart as text content, ImagePart as image_url content,
    FilePart as text reference (fallback).
    """

    def __init__(self, provider: str = "openai") -> None:
        self._provider = provider

    def validate_request(self, messages: list[ChatMessage], **kwargs: object) -> None:
        for msg in messages:
            for part in msg.content:
                if isinstance(part, ImagePart):
                    self._validate_image(part)

    def _validate_image(self, part: ImagePart) -> None:
        if not part.uri:
            raise UnsupportedModalityError(
                modality="image",
                provider=self._provider,
                message="ImagePart has empty uri",
            )

    def encode_messages(
        self, messages: list[ChatMessage], **kwargs: object
    ) -> list[dict[str, object]]:
        self.validate_request(messages)
        return [self.encode(m) for m in messages]

    def encode(self, message: ChatMessage) -> dict[str, object]:
        d: dict[str, object] = {"role": message.role.value}
        parts = []
        for part in message.content:
            if isinstance(part, TextPart):
                parts.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                image_url: dict[str, object] = {"url": part.uri}
                if part.mime_type:
                    image_url["detail"] = "auto"
                parts.append({
                    "type": "image_url",
                    "image_url": image_url,
                })
            elif isinstance(part, type(FilePart)) or type(part).__name__ == "FilePart":
                parts.append({
                    "type": "text",
                    "text": f"[File: {part.filename}] ({part.uri})",
                })
        if parts:
            d["content"] = parts
        else:
            d["content"] = message.get_text() or ""
        if message.tool_call_id:
            d["tool_call_id"] = message.tool_call_id
        if message.name:
            d["name"] = message.name
        return d


class GeminiCodec:
    """Codec for Gemini multimodal models.

    Encodes TextPart, ImagePart, FilePart to Gemini's native format.
    """

    def __init__(self, provider: str = "gemini") -> None:
        self._provider = provider

    def validate_request(self, messages: list[ChatMessage], **kwargs: object) -> None:
        pass

    def encode_messages(
        self, messages: list[ChatMessage], **kwargs: object
    ) -> list[dict[str, object]]:
        return [self.encode(m) for m in messages]

    def encode(self, message: ChatMessage) -> dict[str, object]:
        role_map = {
            "system": "user",
            "user": "user",
            "assistant": "model",
            "tool": "function",
        }
        parts = []
        for part in message.content:
            if isinstance(part, TextPart):
                parts.append({"text": part.text})
            elif isinstance(part, ImagePart):
                uri = part.uri
                if uri.startswith("data:"):
                    parts.append({"inline_data": {"mime_type": part.mime_type, "data": uri.split(",", 1)[-1]}})
                else:
                    parts.append({"file_data": {"file_uri": uri, "mime_type": part.mime_type}})
            elif isinstance(part, type(FilePart)) or type(part).__name__ == "FilePart":
                parts.append({"file_data": {"file_uri": part.uri, "mime_type": part.mime_type}})
        if not parts:
            parts.append({"text": message.get_text() or ""})
        return {
            "role": role_map.get(message.role.value, "user"),
            "parts": parts,
        }


def get_codec_for_provider(provider: str) -> ProviderMessageCodec:
    """Resolve a codec for the given provider name."""
    provider_lower = provider.lower().strip()
    if provider_lower in ("deepseek",):
        return TextOnlyCodec(provider=provider)
    if provider_lower in ("gemini", "google"):
        return GeminiCodec(provider=provider)
    if provider_lower in ("vllm", "qwen-vl", "ollama"):
        return OpenAICompatibleCodec(provider=provider)
    return OpenAICompatibleCodec(provider=provider)
