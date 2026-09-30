"""Screenshot attachments for System 2.

The dashboard sends images as base64 (optionally as data URLs). They are
validated here before reaching Ollama: at most MAX_IMAGES per turn, each at
most MAX_IMAGE_BYTES once decoded, and only PNG, JPEG, WebP or GIF.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Iterable

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024

_DATA_URL = re.compile(r"^data:image/[\w.+-]+;base64,", re.IGNORECASE)


def _image_kind(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def normalize_images(images: Iterable[str] | None) -> list[str]:
    """Return clean base64 strings, or raise ValueError with a user-facing message."""
    items = [i for i in (images or []) if isinstance(i, str) and i.strip()]
    if len(items) > MAX_IMAGES:
        raise ValueError(f"Attach at most {MAX_IMAGES} screenshots per message.")
    clean: list[str] = []
    for n, item in enumerate(items, start=1):
        b64 = re.sub(r"\s+", "", _DATA_URL.sub("", item.strip()))
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"Screenshot {n} is not valid base64 image data.")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"Screenshot {n} is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
        if not _image_kind(raw):
            raise ValueError(f"Screenshot {n} is not a PNG, JPEG, WebP or GIF image.")
        clean.append(b64)
    return clean


def screenshot_note(count: int) -> str:
    """One line telling the model that screenshots are attached."""
    if not count:
        return ""
    noun = "screenshot" if count == 1 else "screenshots"
    return f"The user attached {count} {noun}; use {'it' if count == 1 else 'them'} as context for the request."
