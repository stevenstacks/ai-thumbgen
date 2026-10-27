# No `from __future__ import annotations` here: Typer reads the runtime annotations.
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from PIL import Image

from . import frames as fr
from .config import MAX_INPUT_IMAGES, OUTPUT_SIZE, Settings, load_settings, validate_model, validate_quality
from .errors import ThumbgenError
from .imaging import crop_to_aspect, fit_16_9, prepare_input_image, save_upload_jpeg
from .logo_overlay import overlay_logo
from .prompts import build_edit_prompt, build_initial_prompt
from .providers import PROVIDERS, EditRequest, get_provider
from .references import select_references
from .session import Session, list_sessions, normalize_version_id, now_iso, resolve_session, slugify
from .text_overlay import POSITIONS, find_font, overlay_text

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="YouTube thumbnail generator: gameplay frame -> 16:9 -> AI edit, with versioned iterations.",
)

JsonFlag = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON to stdout.")]
ModelOpt = Annotated[
    Optional[str],
    typer.Option("--model", "-m", help="gpt-image-2 | gpt-image-2.5-flare | gpt-image-2.5-sunburst (default: .env)"),
]
QualityOpt = Annotated[Optional[str], typer.Option("--quality", "-q", help="low | medium | high (default: .env)")]
RefOpt = Annotated[
    Optional[list[Path]], typer.Option("--ref", "-r", help="Extra reference image, any path (repeatable).")
]
ProviderOpt = Annotated[str, typer.Option("--provider", help=f"Image provider: {', '.join(PROVIDERS)}")]
DryRunOpt = Annotated[bool, typer.Option("--dry-run", help="Show the prompt and images without calling the API.")]
SessionArg = Annotated[str, typer.Argument(help="Session name, unique prefix/substring, or 'latest'.")]
FromOpt = Annotated[Optional[str], typer.Option("--from", help="Version to start from, e.g. v2 (default: latest).")]


# ---------------------------------------------------------------- helpers

def _emit(as_json: bool, data: dict, lines: list[str]) -> None:
    if as_json:
        print(json.dumps({"ok": True, **data}, ensure_ascii=False, indent=2))
        return
    print("\n".join(lines))
    for w in data.get("warnings", []):
        print(f"warning: {w}", file=sys.stderr)


def _model_quality(settings: Settings, model: Optional[str], quality: Optional[str]) -> tuple[str, str]:
    return validate_model(model or settings.model), validate_quality(quality or settings.quality)


def _existing_files(paths: Optional[list[Path]], label: str) -> list[Path]:
    out = []
    for p in paths or []:
        p = p.expanduser()
        if not p.is_file():
            raise ThumbgenError(f"{label} not found: {p}")
        out.append(p.resolve())
    return out


def _rel(session: Session, p: Path) -> str:
    try:
        return p.resolve().relative_to(session.path.resolve()).as_posix()
    except ValueError:
        return str(p)


def _plan_images(settings: Settings, target: Optional[Path], session_refs: list[Path], use_defaults: bool):
    slots = MAX_INPUT_IMAGES - (1 if target else 0)
    sel = select_references(session_refs, settings.references_dir if use_defaults else None, slots)
    images = ([target] if target else []) + sel.used
    if not images:
        raise ThumbgenError(
            "Nothing to send: give --video/--image, add --ref images, or put style images in references/. "
            "(Refusing to generate a thumbnail from scratch.)"
        )
    return images, sel


def _history(session: Session, parent_id: str) -> list[str]:
    hist = []
    for v in session.chain(parent_id):
        if v.get("initial"):
            continue
        if v["kind"] == "text-overlay":
            hist.append(f'Text "{v["text_overlay"]["text"]}" was added as an overlay (keep it exactly as is)')
        elif v["kind"] == "logo-overlay":
            hist.append(f'A logo was pasted at {v["logo_overlay"]["pos"]} (keep it exactly as is)')
        else:
            hist.append(v["instruction"])
    return hist


def _save_version_files(session: Session, vid: str, img: Image.Image) -> dict:
    api_size = list(img.size)
    archive = fit_16_9(img, OUTPUT_SIZE)
    archive_path = session.file(f"{vid}.png")
    upload_path = session.file(f"{vid}_1280x720.jpg")
    archive.save(archive_path, "PNG", optimize=True)
    jpeg_quality = save_upload_jpeg(archive, upload_path)
    return {
        "image": archive_path.name,
        "upload": upload_path.name,
        "returned_size": api_size,
        "upload_jpeg_quality": jpeg_quality,
    }


def _version_result(session: Session, v: dict, warnings: list[str]) -> tuple[dict, list[str]]:
    data = {
        "session": session.name,
        "session_dir": str(session.path),
        "version": v["id"],
        "parent": v.get("parent"),
        "image": str(session.file(v["image"])),
        "upload": str(session.file(v["upload"])),
        "warnings": warnings,
    }
    lines = [
        f"session: {session.name}",
        f"created {v['id']} (parent: {v.get('parent') or '-'}, {v['kind']}"
        + (f", {v['model']}/{v['quality']})" if v["kind"] == "ai" else ")"),
        f"  archive: {data['image']}",
        f"  upload : {data['upload']}",
    ]
    return data, lines


def _run_ai(
    settings: Settings,
    session: Session,
    *,
    parent_id: Optional[str],
    instruction: str,
    prompt: str,
    images: list[Path],
    refs: list[Path],
    model: str,
    quality: str,
    provider_name: str,
    initial: bool,
) -> dict:
    provider = get_provider(provider_name)
    inputs = [prepare_input_image(p, session.path / ".inputs") for p in images]
    print(f"calling {provider_name}/{model} (quality={quality}, {len(inputs)} image(s))...", file=sys.stderr)
    result = provider.edit(EditRequest(prompt=prompt, images=inputs, model=model, quality=quality, size=OUTPUT_SIZE))
    vid = session.next_version_id()
    with Image.open(io.BytesIO(result.image_bytes)) as img:
        files = _save_version_files(session, vid, img)
    entry = {
        "id": vid,
        "parent": parent_id,
        "kind": "ai",
        "initial": initial,
        "instruction": instruction,
        "full_prompt": prompt,
        "refs": [_rel(session, r) for r in refs],
        "provider": provider_name,
        "model": model,
        "quality": quality,
        "usage": result.usage,
        "created_at": now_iso(),
        **files,
    }
    session.add_version(entry)
    return entry


def _dry_run_data(session_name: str, prompt: str, images: list[Path], sel, model: str, quality: str, extra: dict):
    return {
        "dry_run": True,
        "session": session_name,
        "model": model,
        "quality": quality,
        "size": f"{OUTPUT_SIZE[0]}x{OUTPUT_SIZE[1]}",
        "images": [str(p) for p in images],
        "references_used": [str(p) for p in sel.used],
        "references_dropped": [str(p) for p in sel.dropped],
        "prompt": prompt,
        "warnings": sel.warnings,
        **extra,
    }


def _dry_run_lines(data: dict) -> list[str]:
    lines = [f"[dry run] {data['model']}/{data['quality']} {data['size']}", "images:"]
    lines += [f"  {i + 1}. {p}" for i, p in enumerate(data["images"])]
    lines += ["prompt:", "-" * 60, data["prompt"], "-" * 60]
    return lines


# ---------------------------------------------------------------- frame tools

@app.command()
def frame(
    video: Annotated[Path, typer.Option("--video", "-v", help="Video file (mp4/mkv, HEVC ok).")],
    at: Annotated[str, typer.Option("--at", "-t", help="Timestamp, e.g. 00:12:34.5 or 754.5")],
    crop_x: Annotated[float, typer.Option(help="Horizontal crop position 0..1 (0.5 = center).")] = 0.5,
    no_crop: Annotated[bool, typer.Option("--no-crop", help="Keep the original aspect ratio.")] = False,
    out: Annotated[Optional[Path], typer.Option(help="Output PNG path.")] = None,
    as_json: JsonFlag = False,
):
    """Extract one frame (cropped to 16:9) for preview or for `new --image`. Free, no API call."""
    s = load_settings()
    info = fr.probe(video, s.ffprobe)
    seconds = fr.parse_timestamp(at)
    stamp = fr.format_timestamp(seconds).replace(":", "-")
    out = out or s.frames_dir / f"{slugify(video.stem)}_{stamp}.png"
    warnings = fr.extract_frame(video, seconds, out, hdr=info["hdr"], ffmpeg=s.ffmpeg)
    with Image.open(out) as img:
        result = img.convert("RGB") if no_crop else crop_to_aspect(img.convert("RGB"), crop_x=crop_x)
        result.save(out, "PNG")
        size = result.size
    data = {"path": str(out.resolve()), "size": list(size), "timestamp": fr.format_timestamp(seconds),
            "video": info, "warnings": warnings}
    _emit(as_json, data, [f"frame: {data['path']} ({size[0]}x{size[1]})"])


@app.command()
def frames(
    video: Annotated[Path, typer.Option("--video", "-v", help="Video file.")],
    start: Annotated[str, typer.Option("--from", help="Range start.")] = "0",
    end: Annotated[Optional[str], typer.Option("--to", help="Range end (default: end of video).")] = None,
    every: Annotated[str, typer.Option(help="Interval, e.g. 10s, 0.5m.")] = "30s",
    cols: Annotated[int, typer.Option(help="Columns in the grid.")] = 4,
    out: Annotated[Optional[Path], typer.Option(help="Output JPG path.")] = None,
    as_json: JsonFlag = False,
):
    """Contact sheet: grid of frames with timestamps, to pick a moment from a long video. Free."""
    s = load_settings()
    t0 = fr.parse_timestamp(start)
    t1 = fr.parse_timestamp(end) if end else None
    step = fr.parse_timestamp(every)
    name = f"{slugify(video.stem)}_{fr.format_timestamp(t0).replace(':', '-')[:8]}_sheet.jpg"
    out = out or s.frames_dir / name
    data = fr.contact_sheet(video, t0, t1, step, out, cols=cols, ffmpeg=s.ffmpeg, ffprobe=s.ffprobe)
    data["path"] = str(Path(data["path"]).resolve())
    _emit(as_json, data, [f"contact sheet: {data['path']} ({len(data['timestamps'])} frames)"])


# ---------------------------------------------------------------- sessions

@app.command()
def new(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="What the thumbnail should look like.")],
    video: Annotated[Optional[Path], typer.Option("--video", "-v", help="Video to take the base frame from.")] = None,
    at: Annotated[Optional[str], typer.Option("--at", "-t", help="Timestamp for --video.")] = None,
    image: Annotated[Optional[Path], typer.Option("--image", "-i", help="Base image (screenshot).")] = None,
    ref: RefOpt = None,
    no_default_refs: Annotated[bool, typer.Option("--no-default-refs", help="Skip references/ for this run.")] = False,
    name: Annotated[Optional[str], typer.Option(help="Session name (default: from prompt).")] = None,
    crop_x: Annotated[float, typer.Option(help="Horizontal crop position 0..1 (0.5 = center).")] = 0.5,
    model: ModelOpt = None,
    quality: QualityOpt = None,
    provider: ProviderOpt = "openai",
    dry_run: DryRunOpt = False,
    as_json: JsonFlag = False,
):
    """Start a new thumbnail session and generate v1.

    Base source is optional: --video + --at, --image, or neither (refs-only: build from --ref images + prompt).
    """
    s = load_settings()
    model, quality = _model_quality(s, model, quality)
    if video and image:
        raise ThumbgenError("Use either --video or --image, not both.")
    if video and not at:
        raise ThumbgenError("--video needs --at <timestamp>.")
    if at and not video:
        raise ThumbgenError("--at needs --video.")
    manual_refs = _existing_files(ref, "Reference")
    use_defaults = not no_default_refs

    warnings: list[str] = []
    if video:
        video = video.expanduser().resolve()
        info = fr.probe(video, s.ffprobe)
        seconds = fr.parse_timestamp(at)
        if info["duration"] and seconds > info["duration"]:
            raise ThumbgenError(f"--at is past the end of the video ({fr.format_timestamp(info['duration'])}).")
        source = {"kind": "video", "path": str(video), "timestamp": fr.format_timestamp(seconds),
                  "crop_x": crop_x, "video": info, "base": "base.png"}
    elif image:
        image = _existing_files([image], "Image")[0]
        source = {"kind": "image", "path": str(image), "crop_x": crop_x, "base": "base.png"}
    else:
        source = {"kind": "refs-only", "base": None}

    session = Session.create(
        s.sessions_dir, name or " ".join(prompt.split()[:6]),
        source=source, brief=prompt, game=s.game, use_default_refs=use_defaults, persist=not dry_run,
    )
    target = session.base_path

    if dry_run:
        images, sel = _plan_images(s, target, manual_refs, use_defaults)
        full_prompt = build_initial_prompt(s.game, prompt, has_base=target is not None, n_refs=len(sel.used))
        data = _dry_run_data(session.name, full_prompt, images, sel, model, quality, {"source": source})
        _emit(as_json, data, _dry_run_lines(data))
        return

    # Build base.png (16:9, 2048x1152) from the source.
    if source["kind"] == "video":
        frame_path = session.file("source_frame.png")
        warnings += fr.extract_frame(video, seconds, frame_path, hdr=info["hdr"], ffmpeg=s.ffmpeg)
        src_img_path = frame_path
    elif source["kind"] == "image":
        src_img_path = image
    if target is not None:
        with Image.open(src_img_path) as img:
            fit_16_9(img, OUTPUT_SIZE, crop_x).save(target, "PNG")

    session.add_refs(manual_refs)
    session.save()
    images, sel = _plan_images(s, target, session.ref_paths(), use_defaults)
    full_prompt = build_initial_prompt(s.game, prompt, has_base=target is not None, n_refs=len(sel.used))
    try:
        v = _run_ai(s, session, parent_id=None, instruction=prompt, prompt=full_prompt, images=images,
                    refs=sel.used, model=model, quality=quality, provider_name=provider, initial=True)
    except ThumbgenError as e:
        raise ThumbgenError(
            f"{e}\nSession kept at {session.path}. Retry with: ai-thumbgen edit {session.name} --prompt \"...\""
        ) from None
    data, lines = _version_result(session, v, warnings + sel.warnings)
    _emit(as_json, data, lines)


@app.command()
def edit(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="The change to make, e.g. 'make the title bigger'.")],
    session_key: SessionArg = "latest",
    from_: FromOpt = None,
    ref: RefOpt = None,
    drop_ref: Annotated[
        Optional[list[str]], typer.Option("--drop-ref", help="Remove a session reference by file name (repeatable).")
    ] = None,
    default_refs: Annotated[
        Optional[bool],
        typer.Option("--default-refs/--no-default-refs", help="Include references/ for this run (default: as in `new`)."),
    ] = None,
    model: ModelOpt = None,
    quality: QualityOpt = None,
    provider: ProviderOpt = "openai",
    dry_run: DryRunOpt = False,
    as_json: JsonFlag = False,
):
    """Create the next version by editing the latest (or --from) version."""
    s = load_settings()
    model, quality = _model_quality(s, model, quality)
    session = resolve_session(s.sessions_dir, session_key)
    new_refs = _existing_files(ref, "Reference")
    use_defaults = session.data["use_default_refs"] if default_refs is None else default_refs

    if from_:
        parent = session.version(from_)
    else:
        parent = session.latest

    # Session refs for this run (dry run: computed without touching the session).
    drops = set(drop_ref or [])
    if dry_run:
        for name in drops:
            if not any(p.name == name for p in session.ref_paths()):
                raise ThumbgenError(f"Session ref '{name}' not found.")
        session_refs = [p for p in session.ref_paths() if p.name not in drops] + new_refs
    else:
        session.drop_refs(list(drops))
        session.add_refs(new_refs)
        session.save()
        session_refs = session.ref_paths()

    if parent is None:
        # Session without versions (e.g. first API call failed): run the initial generation with this prompt.
        target = session.base_path
        images, sel = _plan_images(s, target, session_refs, use_defaults)
        full_prompt = build_initial_prompt(s.game, prompt, has_base=target is not None, n_refs=len(sel.used))
        parent_id, initial = None, True
        if not dry_run:
            session.data["brief"] = prompt
    else:
        target = session.file(parent["image"])
        images, sel = _plan_images(s, target, session_refs, use_defaults)
        full_prompt = build_edit_prompt(
            s.game, session.data["brief"], _history(session, parent["id"]), prompt, n_refs=len(sel.used)
        )
        parent_id, initial = parent["id"], False

    if dry_run:
        data = _dry_run_data(session.name, full_prompt, images, sel, model, quality, {"parent": parent_id})
        _emit(as_json, data, _dry_run_lines(data))
        return

    v = _run_ai(s, session, parent_id=parent_id, instruction=prompt, prompt=full_prompt, images=images,
                refs=sel.used, model=model, quality=quality, provider_name=provider, initial=initial)
    data, lines = _version_result(session, v, sel.warnings)
    _emit(as_json, data, lines)


@app.command()
def text(
    text_: Annotated[str, typer.Option("--text", "-t", help="Text to draw. Use \\n for a line break.")],
    session_key: SessionArg = "latest",
    from_: FromOpt = None,
    pos: Annotated[str, typer.Option(help=" | ".join(POSITIONS))] = "top-left",
    size: Annotated[float, typer.Option(help="Font size as a fraction of image height.")] = 0.18,
    color: Annotated[str, typer.Option(help="Text color.")] = "#ffffff",
    stroke: Annotated[str, typer.Option(help="Outline color.")] = "#000000",
    no_stroke: Annotated[bool, typer.Option("--no-stroke", help="No outline.")] = False,
    stroke_ratio: Annotated[float, typer.Option(help="Outline width relative to font size.")] = 0.07,
    glow: Annotated[Optional[str], typer.Option(help="Glow color, e.g. '#ff2020'.")] = None,
    font: Annotated[Optional[Path], typer.Option(help="TTF/OTF font (default: first in fonts/, else Impact).")] = None,
    margin: Annotated[float, typer.Option(help="Edge margin as a fraction of the image.")] = 0.05,
    as_json: JsonFlag = False,
):
    """Fallback: draw text with Pillow onto a version (no API call). Creates a new version."""
    s = load_settings()
    session = resolve_session(s.sessions_dir, session_key)
    parent = session.version(from_) if from_ else session.latest
    if parent is None:
        raise ThumbgenError("Session has no versions yet.")
    font_path = find_font(font, s.fonts_dir)
    params = {"text": text_, "pos": pos, "size": size, "color": color, "stroke": None if no_stroke else stroke,
              "stroke_ratio": stroke_ratio, "glow": glow, "font": str(font_path) if font_path else None,
              "margin": margin}
    with Image.open(session.file(parent["image"])) as img:
        try:
            result = overlay_text(img, text_, pos=pos, size=size, color=color, stroke=params["stroke"],
                                  stroke_ratio=stroke_ratio, glow=glow, font_path=font_path, margin=margin)
        except ValueError as e:
            raise ThumbgenError(f"Invalid text option: {e}") from None
    vid = session.next_version_id()
    entry = {
        "id": vid,
        "parent": parent["id"],
        "kind": "text-overlay",
        "instruction": f'Pillow text "{text_}" at {pos}',
        "text_overlay": params,
        "created_at": now_iso(),
        **_save_version_files(session, vid, result),
    }
    session.add_version(entry)
    data, lines = _version_result(session, entry, [])
    _emit(as_json, data, lines)


@app.command()
def logo(
    image: Annotated[Path, typer.Option("--image", "-i", help="Logo file (PNG with transparency works best).")],
    session_key: SessionArg = "latest",
    from_: FromOpt = None,
    pos: Annotated[str, typer.Option(help=" | ".join(POSITIONS))] = "top-right",
    width: Annotated[float, typer.Option(help="Logo width as a fraction of image width.")] = 0.3,
    margin: Annotated[float, typer.Option(help="Edge margin as a fraction of the image.")] = 0.04,
    shadow: Annotated[Optional[str], typer.Option(help="Soft shadow/glow color behind the logo, e.g. '#000000'.")] = None,
    opacity: Annotated[float, typer.Option(help="Logo opacity 0..1.")] = 1.0,
    as_json: JsonFlag = False,
):
    """Paste a logo exactly as is onto a version (no API call). Creates a new version."""
    s = load_settings()
    session = resolve_session(s.sessions_dir, session_key)
    parent = session.version(from_) if from_ else session.latest
    if parent is None:
        raise ThumbgenError("Session has no versions yet.")
    logo_path = _existing_files([image], "Logo")[0]
    params = {"image": str(logo_path), "pos": pos, "width": width, "margin": margin, "shadow": shadow,
              "opacity": opacity}
    with Image.open(session.file(parent["image"])) as img, Image.open(logo_path) as mark:
        result = overlay_logo(img, mark, pos=pos, width=width, margin=margin, shadow=shadow, opacity=opacity)
    vid = session.next_version_id()
    entry = {
        "id": vid,
        "parent": parent["id"],
        "kind": "logo-overlay",
        "instruction": f"Pillow logo {logo_path.name} at {pos}",
        "logo_overlay": params,
        "created_at": now_iso(),
        **_save_version_files(session, vid, result),
    }
    session.add_version(entry)
    data, lines = _version_result(session, entry, [])
    _emit(as_json, data, lines)


@app.command("list")
def list_cmd(as_json: JsonFlag = False):
    """List sessions (oldest first, most recently updated last)."""
    s = load_settings()
    sessions = list_sessions(s.sessions_dir)
    rows = []
    for ses in sessions:
        latest = ses.latest
        rows.append({
            "name": ses.name,
            "source": ses.data["source"]["kind"],
            "versions": len(ses.versions),
            "latest": latest["id"] if latest else None,
            "updated_at": ses.data["updated_at"],
            "brief": ses.data["brief"],
        })
    lines = [f"{r['name']}  [{r['source']}]  {r['versions']} version(s), latest {r['latest'] or '-'}"
             f"  ·  {r['updated_at']}\n    {r['brief'][:90]}" for r in rows] or ["(no sessions)"]
    _emit(as_json, {"sessions": rows}, lines)


@app.command()
def show(session_key: SessionArg = "latest", as_json: JsonFlag = False):
    """Show a session's version tree with instructions and file paths."""
    s = load_settings()
    session = resolve_session(s.sessions_dir, session_key)
    versions = [
        {**v, "image_path": str(session.file(v["image"])), "upload_path": str(session.file(v["upload"]))}
        for v in session.versions
    ]
    children: dict = {}
    for v in session.versions:
        children.setdefault(v.get("parent"), []).append(v)

    lines = [
        f"session: {session.name}",
        f"source : {session.data['source']['kind']}"
        + (f"  {session.data['source'].get('path', '')} {session.data['source'].get('timestamp', '')}".rstrip()),
        f"brief  : {session.data['brief']}",
        "refs   : " + (", ".join(p.name for p in session.ref_paths()) or "-")
        + f"  (default refs: {'on' if session.data['use_default_refs'] else 'off'})",
        f"folder : {session.path}",
        "",
    ]

    def walk(parent_id, prefix: str):
        kids = children.get(parent_id, [])
        for i, v in enumerate(kids):
            last = i == len(kids) - 1
            branch = "" if parent_id is None else ("└─ " if last else "├─ ")
            tag = f"{v['model']}/{v['quality']}" if v["kind"] == "ai" else "pillow"
            lines.append(f"{prefix}{branch}{v['id']}  [{tag}]  {v['instruction'][:80]}")
            walk(v["id"], prefix + ("" if parent_id is None else ("   " if last else "│  ")))

    walk(None, "")
    if not session.versions:
        lines.append("(no versions yet)")
    data = {**session.data, "session_dir": str(session.path), "versions": versions}
    _emit(as_json, data, lines)


@app.command("open")
def open_cmd(
    session_key: SessionArg = "latest",
    version: Annotated[Optional[str], typer.Argument(help="Version id (default: latest).")] = None,
    archive: Annotated[bool, typer.Option("--archive", help="Open the 2048x1152 PNG instead of the JPG.")] = False,
):
    """Open a version in the default image viewer."""
    s = load_settings()
    session = resolve_session(s.sessions_dir, session_key)
    v = session.version(normalize_version_id(version)) if version else session.latest
    if v is None:
        raise ThumbgenError("Session has no versions yet.")
    path = session.file(v["image"] if archive else v["upload"])
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)
    print(str(path))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass
    try:
        app()
    except ThumbgenError as e:
        if "--json" in sys.argv:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
