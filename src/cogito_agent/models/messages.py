from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ── Roles ─────────────────────────────────────────────────────────────────


class MessageRole(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


# ── Content Parts ──────────────────────────────────────────────────────────


class ContentPartType(StrEnum):
    text = "text"
    image = "image"
    file = "file"


_ALLOWED_IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
)
_ALLOWED_URI_SCHEMES: frozenset[str] = frozenset(
    {
        "data",
        "file",
        "http",
        "https",
    }
)


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    uri: str = ""
    attachment_id: str | None = None
    mime_type: str = "image/png"
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    trust_level: str = "untrusted"

    def get_uri_or_attachment(self) -> str:
        if self.uri:
            return self.uri
        return f"attachment://{self.attachment_id}" if self.attachment_id else ""

    @model_validator(mode="after")
    def _validate_uri(self) -> ImagePart:
        if not self.uri and not self.attachment_id:
            raise ValueError("ImagePart must have either uri or attachment_id")
        if self.uri:
            if not self.uri.strip():
                raise ValueError("ImagePart uri must not be empty")
            if self.mime_type not in _ALLOWED_IMAGE_MIME_TYPES:
                raise ValueError(
                    f"Unsupported image MIME type '{self.mime_type}'. "
                    f"Allowed: {sorted(_ALLOWED_IMAGE_MIME_TYPES)}"
                )
            scheme = self.uri.split(":", 1)[0] if ":" in self.uri else ""
            if scheme and scheme not in _ALLOWED_URI_SCHEMES:
                raise ValueError(
                    f"Unsupported URI scheme '{scheme}' in ImagePart. "
                    f"Allowed: {sorted(_ALLOWED_URI_SCHEMES)}"
                )
        return self


class FilePart(BaseModel):
    type: Literal["file"] = "file"
    uri: str
    mime_type: str
    filename: str
    sha256: str | None = None


ContentPart = TextPart | ImagePart | FilePart


def normalize_content(content: str | list[dict[str, Any]] | list[ContentPart]) -> list[ContentPart]:
    """Convert various content formats to a canonical list of ContentPart.

    Accepts:
    - A plain string → wrapped as [TextPart]
    - A list of dicts (JSON-style) → each dict validated as a ContentPart
    - A list of ContentPart objects → returned as-is

    Raises ValueError on unknown content part types.
    """
    if isinstance(content, str):
        return [TextPart(text=content)] if content.strip() else []

    parts: list[ContentPart] = []
    for item in content:
        if isinstance(item, dict):
            ptype = item.get("type", "text")
            if ptype == "text":
                parts.append(TextPart(text=str(item.get("text", ""))))
            elif ptype == "image":
                parts.append(ImagePart.model_validate(item))
            elif ptype == "file":
                parts.append(FilePart.model_validate(item))
            else:
                raise ValueError(
                    f"Unknown content part type '{ptype}'. "
                    f"Supported: {[e.value for e in ContentPartType]}"
                )
        elif isinstance(item, (TextPart, ImagePart, FilePart)):
            parts.append(item)
        else:
            raise TypeError(f"Unexpected content part type: {type(item).__name__}")
    return parts


def extract_text(content: list[ContentPart]) -> str:
    """Extract concatenated text from a list of ContentPart."""
    texts: list[str] = []
    for part in content:
        if isinstance(part, TextPart):
            texts.append(part.text)
    return "\n".join(texts)


def has_image(content: list[ContentPart]) -> bool:
    return any(isinstance(p, ImagePart) for p in content)


def has_file(content: list[ContentPart]) -> bool:
    return any(isinstance(p, FilePart) for p in content)


# ── ChatMessage ────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: MessageRole
    content: list[ContentPart] = Field(default_factory=list)
    name: str | None = None
    tool_call_id: str | None = None
    text: str | None = None

    @model_validator(mode="after")
    def _init_content_from_text(self) -> ChatMessage:
        if not self.content and self.text is not None:
            self.content = [TextPart(text=self.text)]
        return self

    def get_text(self) -> str:
        return extract_text(self.content)

    def has_image(self) -> bool:
        return has_image(self.content)

    def has_file(self) -> bool:
        return has_file(self.content)

    def to_legacy_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"role": self.role.value}
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        if len(self.content) == 1 and isinstance(self.content[0], TextPart):
            d["content"] = self.content[0].text
        else:
            d["content"] = [p.model_dump(exclude_none=True) for p in self.content]
        return d

    @staticmethod
    def from_legacy_dict(d: dict[str, object]) -> ChatMessage:
        role_raw = d.get("role", "user")
        role = MessageRole(role_raw) if isinstance(role_raw, str) else MessageRole.user
        content_raw = d.get("content", "")
        tool_call_id = d.get("tool_call_id")
        name = d.get("name")
        if isinstance(content_raw, str):
            return ChatMessage(
                role=role,
                text=str(content_raw) if content_raw.strip() else None,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                name=str(name) if name else None,
            )
        if isinstance(content_raw, list):
            parts = normalize_content(content_raw)
            return ChatMessage(
                role=role,
                content=parts,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                name=str(name) if name else None,
            )
        return ChatMessage(role=role, text=str(content_raw) if content_raw else None)


__all__ = [
    "MessageRole",
    "ContentPartType",
    "TextPart",
    "ImagePart",
    "FilePart",
    "ContentPart",
    "normalize_content",
    "extract_text",
    "has_image",
    "has_file",
    "ChatMessage",
]
