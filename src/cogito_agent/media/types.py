from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class TextContentPart:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass(frozen=True)
class ImageContentPart:
    type: Literal["image"] = "image"
    attachment_id: str = ""
    detail: Literal["auto", "low", "high"] = "auto"


AttachmentInfo = TextContentPart | ImageContentPart


@dataclass
class Attachment:
    id: str
    workspace_id: str
    session_id: str | None
    content_hash: str
    media_type: str
    original_filename: str
    storage_path: str
    size_bytes: int
    width: int | None
    height: int | None
    created_at: datetime


def create_attachment_id() -> str:
    return f"att_{uuid.uuid4().hex[:24]}"


@dataclass
class VisionObservation:
    id: str
    workspace_id: str
    session_id: str | None
    attachment_id: str
    image_content_hash: str
    prompt: str
    normalized_prompt: str
    result_text: str
    provider: str
    model: str
    preprocessing_version: str
    cache_key: str
    created_at: datetime


def create_cache_key(
    workspace_id: str,
    image_content_hash: str,
    normalized_prompt: str,
    vision_provider: str,
    vision_model: str,
    preprocessing_version: str,
) -> str:
    import hashlib
    import json
    stable = json.dumps(
        {
            "w": workspace_id,
            "h": image_content_hash,
            "p": normalized_prompt,
            "v_provider": vision_provider,
            "v_model": vision_model,
            "pv": preprocessing_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()
