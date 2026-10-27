from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .errors import ThumbgenError

POSITIONS = (
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
)
_WINDOWS_FALLBACK_FONTS = ("impact.ttf", "arialbd.ttf", "segoeuib.ttf")
FULL_AREA = (0.0, 0.0, 1.0, 1.0)


def check_pos(pos: str) -> None:
    if pos not in POSITIONS:
        raise ThumbgenError(f"Unknown position '{pos}'. Choose one of: {', '.join(POSITIONS)}")


def place(
    size: tuple[int, int],
    canvas: tuple[int, int],
    pos: str,
    margin: float,
    area: tuple[float, float, float, float] = FULL_AREA,
) -> tuple[int, int]:
    """Top-left corner for a box of `size` at `pos` inside `area` (fractions of the canvas), `margin` from its edges."""
    w, h = size
    W, H = canvas
    ax0, ay0, ax1, ay1 = round(W * area[0]), round(H * area[1]), round(W * area[2]), round(H * area[3])
    mx, my = int((ax1 - ax0) * margin), int((ay1 - ay0) * margin)
    horiz = "left" if pos.endswith("left") else "right" if pos.endswith("right") else "center"
    vert = "top" if pos.startswith("top") else "bottom" if pos.startswith("bottom") else "middle"
    x = {"left": ax0 + mx, "center": (ax0 + ax1 - w) // 2, "right": ax1 - mx - w}[horiz]
    y = {"top": ay0 + my, "middle": (ay0 + ay1 - h) // 2, "bottom": ay1 - my - h}[vert]
    return x, y


def find_font(explicit: Path | None, fonts_dir: Path | None) -> Path | None:
    """Explicit --font, else first .ttf/.otf in fonts/, else Impact/Arial Bold from Windows."""
    if explicit:
        if not explicit.is_file():
            raise ThumbgenError(f"Font not found: {explicit}")
        return explicit
    if fonts_dir and fonts_dir.is_dir():
        found = sorted(p for p in fonts_dir.iterdir() if p.suffix.lower() in (".ttf", ".otf"))
        if found:
            return found[0]
    win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in _WINDOWS_FALLBACK_FONTS:
        if (win_fonts / name).is_file():
            return win_fonts / name
    return None


def load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path is None:
        path = find_font(None, None)
    if path is None:
        return ImageFont.load_default(size=size)
    return ImageFont.truetype(str(path), size)


def overlay_text(
    img: Image.Image,
    text: str,
    *,
    pos: str = "top-left",
    size: float = 0.18,
    color: str = "#ffffff",
    stroke: str | None = "#000000",
    stroke_ratio: float = 0.07,
    glow: str | None = None,
    font_path: Path | None = None,
    margin: float = 0.05,
    area: tuple[float, float, float, float] = FULL_AREA,
) -> Image.Image:
    """Draw bold thumbnail text inside `area`. `size` is the font size as a fraction of the shorter image side."""
    check_pos(pos)
    base = img.convert("RGBA")
    W, H = base.size
    font_size = max(8, int(min(W, H) * size))
    font = load_font(font_path, font_size)
    sw = max(1, int(font_size * stroke_ratio)) if stroke else 0
    text = text.replace("\\n", "\n")
    align = "left" if pos.endswith("left") else "right" if pos.endswith("right") else "center"

    l, t, r, b = ImageDraw.Draw(base).multiline_textbbox((0, 0), text, font=font, stroke_width=sw, align=align)
    x, y = place((r - l, b - t), (W, H), pos, margin, area)
    x, y = x - l, y - t

    if glow:
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).multiline_text(
            (x, y), text, font=font, fill=glow, align=align,
            stroke_width=sw + int(font_size * 0.08), stroke_fill=glow,
        )
        layer = layer.filter(ImageFilter.GaussianBlur(font_size * 0.22))
        base = Image.alpha_composite(base, layer)
        base = Image.alpha_composite(base, layer)

    ImageDraw.Draw(base).multiline_text(
        (x, y), text, font=font, fill=color, align=align, stroke_width=sw, stroke_fill=stroke,
    )
    return base.convert("RGB")
