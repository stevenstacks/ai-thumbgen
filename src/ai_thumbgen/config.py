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

UPLOAD_MAX_BYTES = 2 * 1024 * 1024  # YouTube custom thumbnail limit; also used for TikTok covers


@dataclass(frozen=True)
class Format:
    name: str
    noun: str  # what the prompt calls the output
    label: str  # output description in the prompt
    api_size: tuple[int, int]  # sent to the model; gpt-image-2 wants multiples of 16, <= 2560x1440 pixels
    uploads: tuple[tuple[int, int], ...]  # JPGs written per version; the first one is the main upload
    safe_area: tuple[float, float, float, float]  # left, top, right, bottom (fractions) for text and logos
    prompt_note: str = ""

    @property
    def aspect(self) -> float:
        return self.api_size[0] / self.api_size[1]


FORMATS = {
    "youtube": Format(
        name="youtube",
        noun="YouTube thumbnail",
        label="16:9 YouTube thumbnail",
        api_size=(2048, 1152),
        uploads=((1280, 720),),
        safe_area=(0.0, 0.0, 1.0, 1.0),
    ),
    # TikTok shows covers at 9:16, but the profile grid and the desktop cover upload crop them to 3:4.
    "tiktok": Format(
        name="tiktok",
        noun="TikTok cover",
        label="9:16 vertical TikTok cover",
        api_size=(1152, 2048),
        uploads=((1080, 1920), (1080, 1440)),
        safe_area=(0.0, 0.125, 1.0, 0.875),
        prompt_note=(
            "Keep all text, logos and faces inside the central 3:4 area (the middle 75% of the height), "
            "because TikTok crops covers to 3:4 in the profile grid. Leave the top and bottom eighths "
            "free of text and logos; extend the background there."
        ),
    ),
}
DEFAULT_FORMAT = "youtube"


def get_format(name: str | None) -> Format:
    try:
        return FORMATS[name or DEFAULT_FORMAT]
    except KeyError:
        raise ThumbgenError(f"Unknown format '{name}'. Choose one of: {', '.join(FORMATS)}") from None

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
    ref_set: str  # default subfolder of references/ ("" = the top level)
    max_refs: int | None
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
        ref_set=os.getenv("THUMBGEN_REFS", "").strip(),
        max_refs=validate_max_refs(int(os.environ["THUMBGEN_MAX_REFS"])) if os.getenv("THUMBGEN_MAX_REFS") else None,
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


def validate_max_refs(n: int | None) -> int | None:
    if n is not None and not 0 <= n <= MAX_INPUT_IMAGES - 1:
        raise ThumbgenError(f"--max-refs must be between 0 and {MAX_INPUT_IMAGES - 1}.")
    return n


def require_openai_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise ThumbgenError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env, open it in an editor "
            "and fill in OPENAI_API_KEY=... yourself. Never paste the key into a chat."
        )
    return key
