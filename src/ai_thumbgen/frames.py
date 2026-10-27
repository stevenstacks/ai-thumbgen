from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

from .errors import ThumbgenError
from .imaging import ASPECT_16_9
from .text_overlay import load_font

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
# HDR (PQ/HLG) -> SDR bt709, otherwise OBS HDR captures look washed out.
TONEMAP_VF = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=rgb24"
)
MAX_SHEET_FRAMES = 120


def find_tool(name: str, override: str | None) -> str:
    path = override or shutil.which(name)
    if not path:
        raise ThumbgenError(
            f"{name} not found on PATH. Install it with `winget install -e --id Gyan.FFmpeg` "
            f"and open a new terminal, or set THUMBGEN_{name.upper()} in .env."
        )
    return path


def parse_timestamp(value: str) -> float:
    """Accepts '754.5', '90s', '2m', '12:34', '00:12:34.500'. Returns seconds."""
    s = value.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", s)
    if m:
        num, unit = float(m.group(1)), m.group(2) or "s"
        return num * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    parts = s.split(":")
    if 2 <= len(parts) <= 3:
        try:
            total = 0.0
            for p in parts:
                total = total * 60 + float(p)
            return total
        except ValueError:
            pass
    raise ThumbgenError(f"Invalid timestamp '{value}'. Use e.g. 00:12:34.5, 12:34, 754.5 or 90s.")


def format_timestamp(seconds: float) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def probe(video: Path, ffprobe: str | None = None) -> dict:
    exe = find_tool("ffprobe", ffprobe)
    if not video.is_file():
        raise ThumbgenError(f"Video not found: {video}")
    cmd = [
        exe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,pix_fmt,color_transfer:format=duration",
        "-of", "json", str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ThumbgenError(f"ffprobe failed: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise ThumbgenError(f"No video stream in {video}")
    st = streams[0]
    return {
        "width": st.get("width"),
        "height": st.get("height"),
        "codec": st.get("codec_name"),
        "pix_fmt": st.get("pix_fmt"),
        "color_transfer": st.get("color_transfer"),
        "hdr": st.get("color_transfer") in HDR_TRANSFERS,
        "duration": float(data.get("format", {}).get("duration") or 0.0),
    }


def extract_frame(
    video: Path,
    seconds: float,
    out: Path,
    *,
    hdr: bool,
    scale_width: int | None = None,
    ffmpeg: str | None = None,
) -> list[str]:
    """Extract one frame as PNG. Returns warnings."""
    exe = find_tool("ffmpeg", ffmpeg)
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    def run(tonemap: bool) -> subprocess.CompletedProcess:
        vf = [TONEMAP_VF] if tonemap else []
        if scale_width:
            vf.append(f"scale={scale_width}:-2")
        # -ss before -i: fast keyframe seek, then ffmpeg decodes forward to the exact time.
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{seconds:.3f}", "-i", str(video),
               "-frames:v", "1"]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += ["-pix_fmt", "rgb24", str(out)]
        return subprocess.run(cmd, capture_output=True, text=True)

    proc = run(hdr)
    if proc.returncode != 0 and hdr:
        warnings.append(f"HDR tonemap failed ({proc.stderr.strip()[:120]}); extracted without tonemap.")
        proc = run(False)
    if proc.returncode != 0:
        raise ThumbgenError(f"ffmpeg failed: {proc.stderr.strip()}")
    if not out.is_file():
        raise ThumbgenError(f"No frame at {format_timestamp(seconds)} (past the end of the video?)")
    return warnings


def contact_sheet(
    video: Path,
    start: float,
    end: float | None,
    every: float,
    out: Path,
    *,
    cols: int = 4,
    thumb_width: int = 480,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> dict:
    """Grid of frames with timestamp labels; dashed lines mark the centered 16:9 crop."""
    info = probe(video, ffprobe)
    duration = info["duration"]
    end = min(end, duration) if end is not None else duration
    if every <= 0:
        raise ThumbgenError("--every must be > 0")
    if end <= start:
        raise ThumbgenError(f"Range is empty (video duration is {format_timestamp(duration)})")
    times = []
    t = start
    while t < end and len(times) <= MAX_SHEET_FRAMES:
        times.append(t)
        t += every
    if len(times) > MAX_SHEET_FRAMES:
        raise ThumbgenError(
            f"That is more than {MAX_SHEET_FRAMES} frames. Narrow --from/--to or increase --every."
        )

    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / f"f{i:04d}.png" for i in range(len(times))]

        def grab(i: int) -> list[str]:
            try:
                return extract_frame(
                    video, times[i], paths[i], hdr=info["hdr"], scale_width=thumb_width, ffmpeg=ffmpeg
                )
            except ThumbgenError as e:
                return [str(e)]

        with ThreadPoolExecutor(max_workers=4) as pool:
            for w in pool.map(grab, range(len(times))):
                warnings.extend(w)

        pairs = [(Image.open(p).convert("RGB"), ts) for p, ts in zip(paths, times) if p.is_file()]
        if not pairs:
            raise ThumbgenError("No frames could be extracted.")
        thumbs, times = [p[0] for p in pairs], [p[1] for p in pairs]
        tw, th = thumbs[0].size
        rows = -(-len(thumbs) // cols)
        gap = 6
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * gap, rows * th + (rows + 1) * gap), (20, 20, 20))
        font = load_font(None, max(14, th // 9))
        crop_w = round(th * ASPECT_16_9)
        for i, (thumb, ts) in enumerate(zip(thumbs, times)):
            x = gap + (i % cols) * (tw + gap)
            y = gap + (i // cols) * (th + gap)
            draw = ImageDraw.Draw(thumb)
            if crop_w < tw:
                left = (tw - crop_w) // 2
                for cx in (left, left + crop_w):
                    for yy in range(0, th, 8):
                        draw.line([(cx, yy), (cx, yy + 4)], fill=(255, 255, 0), width=1)
            label = format_timestamp(ts)[:-4]  # HH:MM:SS
            box = draw.textbbox((6, 4), label, font=font)
            draw.rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2), fill=(0, 0, 0))
            draw.text((6, 4), label, font=font, fill=(255, 255, 255))
            sheet.paste(thumb, (x, y))
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, "JPEG", quality=88)
        for t_img in thumbs:
            t_img.close()

    return {
        "path": str(out),
        "timestamps": [format_timestamp(t) for t in times],
        "video": info,
        "warnings": sorted(set(warnings)),
    }
