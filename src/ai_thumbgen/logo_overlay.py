from __future__ import annotations

from PIL import Image, ImageColor, ImageFilter

from .errors import ThumbgenError
from .text_overlay import FULL_AREA, check_pos, place


def overlay_logo(
    img: Image.Image,
    logo: Image.Image,
    *,
    pos: str = "top-right",
    width: float = 0.3,
    margin: float = 0.04,
    shadow: str | None = None,
    opacity: float = 1.0,
    area: tuple[float, float, float, float] = FULL_AREA,
) -> Image.Image:
    """Paste a logo pixel-exact (alpha kept) inside `area`. `width` is the logo width as a fraction of image width."""
    check_pos(pos)
    if not 0 < width <= 1:
        raise ThumbgenError("--width must be between 0 and 1.")
    if not 0 < opacity <= 1:
        raise ThumbgenError("--opacity must be between 0 and 1.")
    base = img.convert("RGBA")
    W, H = base.size
    mark = logo.convert("RGBA")
    # Trim fully transparent padding so position and width refer to the visible logo.
    bbox = mark.getchannel("A").getbbox()
    if bbox is None:
        raise ThumbgenError("Logo image is fully transparent.")
    mark = mark.crop(bbox)
    lw = max(1, int(W * width))
    lh = max(1, round(mark.height * lw / mark.width))
    if lh > H * (area[3] - area[1]):
        raise ThumbgenError("Logo is too tall at this --width; use a smaller value.")
    mark = mark.resize((lw, lh), Image.LANCZOS)
    if opacity < 1:
        mark.putalpha(mark.getchannel("A").point(lambda a: int(a * opacity)))

    x, y = place((lw, lh), (W, H), pos, margin, area)

    if shadow:
        try:
            rgb = ImageColor.getrgb(shadow)[:3]
        except ValueError as e:
            raise ThumbgenError(f"Invalid shadow color: {e}") from None
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        tint = Image.new("RGBA", mark.size, (*rgb, 255))
        tint.putalpha(mark.getchannel("A"))
        layer.paste(tint, (x, y), tint)
        layer = layer.filter(ImageFilter.GaussianBlur(max(2, lw * 0.03)))
        base = Image.alpha_composite(base, layer)

    base.alpha_composite(mark, (x, y))
    return base.convert("RGB")
