from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class MessageRole(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class ContentPartType(StrEnum):
    text = "text"
    image = "image"
    file = "file"


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    uri: str
    mime_type: str = "image/png"
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    trust_level: Literal["untrusted", "trusted"] = "untrusted"


class FilePart(BaseModel):
    type: Literal["file"] = "file"
    uri: str
    mime_type: str
    filename: str
    sha256: str | None = None


ContentPart = Union[TextPart, ImagePart, FilePart]


class ChatMessage(BaseModel):
    role: MessageRole
    content: list[ContentPart] = Field(default_factory=list)
    name: str | None = None
    tool_call_id: str | None = None
    text: str | None = None

    def model_post_init(self, __context: object) -> None:
        if not self.content and self.text:
            self.content = [TextPart(text=self.text)]
        if not self.content and not self.text:
            self.text = ""
            self.content = []

    def get_text(self) -> str:
        parts: list[str] = []
        for part in self.content:
            if isinstance(part, TextPart):
                parts.append(part.text)
        return "\n".join(parts)

    def has_image(self) -> bool:
        return any(isinstance(p, ImagePart) for p in self.content)

    def has_file(self) -> bool:
        return any(isinstance(p, FilePart) for p in self.content)

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
        role = (
            MessageRole(role_raw)
            if isinstance(role_raw, str)
            else MessageRole.user
        )
        content_raw = d.get("content", "")
        tool_call_id = d.get("tool_call_id")
        name = d.get("name")
        if isinstance(content_raw, str):
            if content_raw.strip():
                return ChatMessage(
                    role=role,
                    text=str(content_raw),
                    tool_call_id=str(tool_call_id) if tool_call_id else None,
                    name=str(name) if name else None,
                )
            return ChatMessage(
                role=role,
                content=[],
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                name=str(name) if name else None,
            )
        if isinstance(content_raw, list):
            parts: list[ContentPart] = []
            for item in content_raw:
                if not isinstance(item, dict):
                    continue
                ptype = item.get("type", "text")
                if ptype == "image":
                    parts.append(ImagePart.model_validate(item))
                elif ptype == "file":
                    parts.append(FilePart.model_validate(item))
                else:
                    parts.append(
                        TextPart(text=str(item.get("text", "")))
                    )
            return ChatMessage(
                role=role,
                content=parts,
                tool_call_id=str(tool_call_id) if tool_call_id else None,
                name=str(name) if name else None,
            )
        return ChatMessage(role=role, text=str(content_raw))
