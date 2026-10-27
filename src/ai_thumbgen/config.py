from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import ThumbgenError

# src/ai_thumbgen/config.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODELS = ("gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst")
QUALITIES = ("low", "medium", "high")

# gpt-image-2 accepts WxH sizes that are multiples of 16; 2048x1152 is 16:9 and non-experimental.
OUTPUT_SIZE = (2048, 1152)
UPLOAD_SIZE = (1280, 720)
UPLOAD_MAX_BYTES = 2 * 1024 * 1024  # YouTube custom thumbnail limit

# OpenAI images.edit: up to 16 input images, each png/webp/jpg < 50MB.
MAX_INPUT_IMAGES = 16
MAX_INPUT_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    root: Path
    output_dir: Path
    sessions_dir: Path
    frames_dir: Path
    references_dir: Path
    fonts_dir: Path
    model: str
    quality: str
    game: str
    ffmpeg: str | None
    ffprobe: str | None


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    root = Path(os.getenv("THUMBGEN_ROOT", PROJECT_ROOT))
    output_dir = root / "output"
    return Settings(
        root=root,
        output_dir=output_dir,
        sessions_dir=output_dir / "sessions",
        frames_dir=output_dir / "frames",
        references_dir=root / "references",
        fonts_dir=root / "fonts",
        model=validate_model(os.getenv("THUMBGEN_MODEL", "gpt-image-2")),
        quality=validate_quality(os.getenv("THUMBGEN_QUALITY", "medium")),
        game=os.getenv("THUMBGEN_GAME", "").strip(),
        ffmpeg=os.getenv("THUMBGEN_FFMPEG") or None,
        ffprobe=os.getenv("THUMBGEN_FFPROBE") or None,
    )


def validate_model(model: str) -> str:
    if model not in MODELS:
        raise ThumbgenError(f"Unknown model '{model}'. Choose one of: {', '.join(MODELS)}")
    return model


def validate_quality(quality: str) -> str:
    if quality not in QUALITIES:
        raise ThumbgenError(f"Unknown quality '{quality}'. Choose one of: {', '.join(QUALITIES)}")
    return quality


def require_openai_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise ThumbgenError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env, open it in an editor "
            "and fill in OPENAI_API_KEY=... yourself. Never paste the key into a chat."
        )
    return key
