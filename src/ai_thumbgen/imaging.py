from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from .config import MAX_INPUT_BYTES, OUTPUT_SIZE, UPLOAD_MAX_BYTES, UPLOAD_SIZE

ALLOWED_INPUT_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ASPECT_16_9 = 16 / 9


def crop_to_aspect(img: Image.Image, aspect: float = ASPECT_16_9, crop_x: float = 0.5) -> Image.Image:
    """Crop to `aspect`. For wide frames (21:9) `crop_x` picks the horizontal window: 0=left, 0.5=center, 1=right."""
    if not 0.0 <= crop_x <= 1.0:
        raise ValueError("crop_x must be between 0.0 and 1.0")
    w, h = img.size
    if abs(w / h - aspect) < 0.01:
        return img
    if w / h > aspect:
        new_w = round(h * aspect)
        left = round((w - new_w) * crop_x)
        return img.crop((left, 0, left + new_w, h))
    new_h = round(w / aspect)
    top = (h - new_h) // 2
    return img.crop((0, top, w, top + new_h))


def fit_16_9(img: Image.Image, size: tuple[int, int] = OUTPUT_SIZE, crop_x: float = 0.5) -> Image.Image:
    img = crop_to_aspect(img.convert("RGB"), ASPECT_16_9, crop_x)
    if img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return img


def save_upload_jpeg(
    img: Image.Image,
    path: Path,
    size: tuple[int, int] = UPLOAD_SIZE,
    max_bytes: int = UPLOAD_MAX_BYTES,
) -> int:
    """Save a YouTube-ready JPEG, lowering quality until it fits under `max_bytes`. Returns the quality used."""
    img = fit_16_9(img, size)
    data = b""
    quality = 95
    for quality in range(95, 49, -5):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            break
    path.write_bytes(data)
    return quality


def prepare_input_image(path: Path, work_dir: Path) -> Path:
    """Return a path the API accepts (png/jpg/webp, < 50MB), converting into `work_dir` if needed."""
    if path.suffix.lower() in ALLOWED_INPUT_EXTS and path.stat().st_size < MAX_INPUT_BYTES:
        return path
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / f"{path.stem}_{file_sha1(path)[:8]}.png"
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((3840, 3840), Image.Resampling.LANCZOS)
        img.save(out, "PNG", optimize=True)
    if out.stat().st_size >= MAX_INPUT_BYTES:
        out = out.with_suffix(".jpg")
        with Image.open(path) as img:
            img.convert("RGB").save(out, "JPEG", quality=92)
    return out


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
