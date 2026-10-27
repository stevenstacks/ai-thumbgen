from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..errors import ThumbgenError


class ProviderError(ThumbgenError):
    pass


@dataclass
class EditRequest:
    prompt: str
    images: list[Path]  # images[0] is the image being edited (or the first reference in refs-only mode)
    model: str
    quality: str
    size: tuple[int, int]


@dataclass
class EditResult:
    image_bytes: bytes
    usage: dict | None = None
    meta: dict = field(default_factory=dict)


class ImageProvider(Protocol):
    name: str
    max_input_images: int

    def edit(self, request: EditRequest) -> EditResult: ...
