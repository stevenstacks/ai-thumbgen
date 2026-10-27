from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .imaging import ALLOWED_INPUT_EXTS, file_sha1

# Accept a few more formats for references; they get converted before upload.
REFERENCE_EXTS = ALLOWED_INPUT_EXTS | {".bmp", ".tif", ".tiff"}


@dataclass
class RefSelection:
    used: list[Path] = field(default_factory=list)
    dropped: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in REFERENCE_EXTS)


def select_references(session_refs: list[Path], default_dir: Path | None, slots: int) -> RefSelection:
    """Session (manual) refs first, then default refs; dedupe by content; cap at `slots`."""
    candidates = list(session_refs) + (list_images(default_dir) if default_dir else [])
    seen: set[str] = set()
    unique: list[Path] = []
    for p in candidates:
        digest = file_sha1(p)
        if digest not in seen:
            seen.add(digest)
            unique.append(p)
    sel = RefSelection(used=unique[:slots], dropped=unique[slots:])
    if sel.dropped:
        sel.warnings.append(
            f"{len(sel.dropped)} reference image(s) skipped (max {slots} per request): "
            + ", ".join(p.name for p in sel.dropped)
        )
    return sel
