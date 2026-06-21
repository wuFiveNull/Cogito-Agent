from __future__ import annotations

import base64
import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:
    Image = None  # type: ignore[assignment]
    UnidentifiedImageError = Exception  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

MEDIA_PREPROCESSING_VERSION = "image-v1"

# Default limits
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_PROVIDER_PAYLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB
MAX_EDGE = 4096
MAX_PIXELS = 40_000_000

# Supported MIME types
SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }
)

# Magic bytes for MIME detection
_MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",
}


def detect_mime_from_bytes(data: bytes) -> str:
    for magic, mime in _MAGIC_BYTES.items():
        if data.startswith(magic):
            if mime == "image/webp":
                if data[8:12] == b"WEBP":
                    return "image/webp"
                continue
            return mime
    raise ValueError("Unable to detect image type from content")


def normalize_prompt(prompt: str) -> str:
    """Conservative prompt normalization for cache key matching."""
    text = unicodedata.normalize("NFKC", prompt)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(".?!")
    text = text.strip()
    return text.lower()


@dataclass
class PreparedImage:
    data: bytes = field(repr=False)
    mime_type: str
    width: int
    height: int
    original_bytes: int
    provider_bytes: int
    original_mime: str
    original_width: int
    original_height: int


class ImageValidationError(ValueError):
    pass


class ImageTooLargeError(ImageValidationError):
    pass


class UnsupportedImageTypeError(ImageValidationError):
    pass


class CorruptImageError(ImageValidationError):
    pass


class MediaProcessor:
    """Centralized image validation and preprocessing pipeline."""

    def __init__(
        self,
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        max_provider_payload_bytes: int = MAX_PROVIDER_PAYLOAD_BYTES,
        max_edge: int = MAX_EDGE,
        max_pixels: int = MAX_PIXELS,
    ) -> None:
        self._max_upload_bytes = max_upload_bytes
        self._max_provider_payload_bytes = max_provider_payload_bytes
        self._max_edge = max_edge
        self._max_pixels = max_pixels

    def validate_and_prepare(
        self,
        data: bytes,
        filename: str = "",
    ) -> PreparedImage:
        """Validate image bytes and prepare for model consumption.

        Steps:
        1. Check file size
        2. Detect MIME from magic bytes
        3. Validate extension matches
        4. Open with Pillow (decompression bomb protection)
        5. EXIF orientation correction
        6. RGBA → RGB conversion
        7. Dimension limits
        8. Downscaling if needed
        9. Provider payload size control

        Returns:
            PreparedImage ready for model serialization.
        """
        # 1. File size
        if len(data) > self._max_upload_bytes:
            raise ImageTooLargeError(
                f"Image size {len(data)} exceeds maximum upload size {self._max_upload_bytes}"
            )

        # 2. Detect MIME
        try:
            detected_mime = detect_mime_from_bytes(data)
        except ValueError as e:
            raise UnsupportedImageTypeError(str(e)) from e

        if detected_mime not in SUPPORTED_IMAGE_TYPES:
            raise UnsupportedImageTypeError(
                f"Unsupported image type '{detected_mime}'. "
                f"Supported: {sorted(SUPPORTED_IMAGE_TYPES)}"
            )

        # 3. Extension validation
        if filename:
            ext = Path(filename).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                raise UnsupportedImageTypeError(
                    f"File extension '{ext}' not in supported types: {sorted(SUPPORTED_EXTENSIONS)}"
                )

        # 4. Pillow open
        if Image is None:
            raise RuntimeError("Pillow is not installed. Install with: pip install Pillow")

        try:
            img: Image.Image = Image.open(io.BytesIO(data))
            img.load()
        except (UnidentifiedImageError, Exception) as e:
            raise CorruptImageError(f"Cannot open image: {e}") from e

        original_width, original_height = img.size

        # 5. EXIF orientation
        try:
            exif = img.getexif()
            orientation = exif.get(0x0112, 1)
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)
        except Exception:
            pass

        # 6. RGBA → RGB
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size

        # 7. Dimension limits
        if width > self._max_edge or height > self._max_edge:
            ratio = min(self._max_edge / width, self._max_edge / height)
            new_w = int(width * ratio)
            new_h = int(height * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            width, height = new_w, new_h

        if width * height > self._max_pixels:
            ratio = (self._max_pixels / (width * height)) ** 0.5
            new_w = int(width * ratio)
            new_h = int(height * ratio)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            width, height = new_w, new_h

        # 8. Encode to JPEG for consistent provider payload
        buf = io.BytesIO()
        quality = 95
        img.save(buf, format="JPEG", quality=quality)
        provider_data = buf.getvalue()

        # 9. Provider payload size control
        attempts = 0
        while len(provider_data) > self._max_provider_payload_bytes and attempts < 5:
            quality = max(10, quality - 15)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            provider_data = buf.getvalue()
            attempts += 1

        if len(provider_data) > self._max_provider_payload_bytes:
            ratio = (self._max_provider_payload_bytes / len(provider_data)) ** 0.5
            new_w = max(64, int(width * ratio))
            new_h = max(64, int(height * ratio))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            provider_data = buf.getvalue()

        return PreparedImage(
            data=provider_data,
            mime_type="image/jpeg",
            width=width,
            height=height,
            original_bytes=len(data),
            provider_bytes=len(provider_data),
            original_mime=detected_mime,
            original_width=original_width,
            original_height=original_height,
        )

    def to_data_uri(self, prepared: PreparedImage) -> str:
        """Convert PreparedImage to data URI for provider."""
        b64 = base64.b64encode(prepared.data).decode("ascii")
        return f"data:{prepared.mime_type};base64,{b64}"

    def get_dimensions(self, data: bytes) -> tuple[int, int]:
        """Get image dimensions without full processing."""
        if Image is None:
            return (0, 0)
        try:
            img = Image.open(io.BytesIO(data))
            return img.size
        except Exception:
            return (0, 0)
