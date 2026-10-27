from __future__ import annotations

from collections.abc import Callable

from ..config import require_openai_key
from ..errors import ThumbgenError
from .base import EditRequest, EditResult, ImageProvider, ProviderError


def _openai() -> ImageProvider:
    from .openai_images import OpenAIImagesProvider

    return OpenAIImagesProvider(require_openai_key())


# Add new providers here (e.g. "gemini": _gemini) implementing the ImageProvider protocol.
PROVIDERS: dict[str, Callable[[], ImageProvider]] = {
    "openai": _openai,
}


def get_provider(name: str) -> ImageProvider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise ThumbgenError(f"Unknown provider '{name}'. Available: {', '.join(PROVIDERS)}") from None


__all__ = ["EditRequest", "EditResult", "ImageProvider", "ProviderError", "PROVIDERS", "get_provider"]
