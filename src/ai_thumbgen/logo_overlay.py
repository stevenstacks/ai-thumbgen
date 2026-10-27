from __future__ import annotations

from PIL import Image, ImageColor, ImageFilter

from .errors import ThumbgenError
from .text_overlay import POSITIONS


def overlay_logo(
    img: Image.Image,
    logo: Image.Image,
    *,
    pos: str = "top-right",
    width: float = 0.3,
    margin: float = 0.04,
    shadow: str | None = None,
    opacity: float = 1.0,
) -> Image.Image:
    """Paste a logo pixel-exact (alpha kept). `width` is the logo width as a fraction of image width."""
    if pos not in POSITIONS:
        raise ThumbgenError(f"Unknown position '{pos}'. Choose one of: {', '.join(POSITIONS)}")
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
    if lh > H:
        raise ThumbgenError("Logo is too tall at this --width; use a smaller value.")
    mark = mark.resize((lw, lh), Image.LANCZOS)
    if opacity < 1:
        mark.putalpha(mark.getchannel("A").point(lambda a: int(a * opacity)))

    mx, my = int(W * margin), int(H * margin)
    horiz = "left" if pos.endswith("left") else "right" if pos.endswith("right") else "center"
    vert = "top" if pos.startswith("top") else "bottom" if pos.startswith("bottom") else "middle"
    x = {"left": mx, "center": (W - lw) // 2, "right": W - mx - lw}[horiz]
    y = {"top": my, "middle": (H - lh) // 2, "bottom": H - my - lh}[vert]

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
