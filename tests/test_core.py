import random
from pathlib import Path

import pytest
from PIL import Image

from ai_thumbgen.errors import ThumbgenError
from ai_thumbgen.frames import format_timestamp, parse_timestamp
from ai_thumbgen.imaging import crop_to_aspect, save_upload_jpeg
from ai_thumbgen.references import select_references
from ai_thumbgen.session import Session, resolve_session


def _img(path: Path, size=(64, 36), color=(255, 0, 0)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def test_crop_ultrawide_center_and_offset():
    img = Image.new("RGB", (3440, 1440))
    assert crop_to_aspect(img).size == (2560, 1440)
    # center crop starts at (3440-2560)/2 = 440
    marked = Image.new("RGB", (3440, 1440))
    marked.putpixel((440, 0), (255, 255, 255))
    assert crop_to_aspect(marked).getpixel((0, 0)) == (255, 255, 255)
    marked.putpixel((0, 0), (1, 2, 3))
    assert crop_to_aspect(marked, crop_x=0.0).getpixel((0, 0)) == (1, 2, 3)


def test_crop_already_16_9_and_tall():
    assert crop_to_aspect(Image.new("RGB", (1920, 1080))).size == (1920, 1080)
    assert crop_to_aspect(Image.new("RGB", (1000, 1000))).size == (1000, 562)


def test_upload_jpeg_under_limit(tmp_path):
    rnd = random.Random(0)
    noisy = Image.frombytes("RGB", (2048, 1152), bytes(rnd.getrandbits(8) for _ in range(2048 * 1152 * 3)))
    out = tmp_path / "u.jpg"
    save_upload_jpeg(noisy, out)
    assert out.stat().st_size <= 2 * 1024 * 1024
    with Image.open(out) as im:
        assert im.size == (1280, 720)


@pytest.mark.parametrize(
    "value,expected",
    [("754.5", 754.5), ("90s", 90), ("2m", 120), ("12:34", 754), ("00:12:34.5", 754.5), ("1:00:00", 3600)],
)
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == pytest.approx(expected)


def test_parse_timestamp_invalid():
    with pytest.raises(ThumbgenError):
        parse_timestamp("abc")


def test_format_timestamp():
    assert format_timestamp(754.5) == "00:12:34.500"


def test_select_references_order_dedupe_cap(tmp_path):
    defaults = tmp_path / "references"
    defaults.mkdir()
    for i in range(20):
        _img(defaults / f"d{i:02d}.png", color=(i, 0, 0))
    manual = _img(tmp_path / "manual.png", color=(0, 0, 255))
    dup = _img(tmp_path / "dup.png", color=(0, 0, 0))  # same content as d00
    sel = select_references([manual, dup], defaults, slots=15)
    assert sel.used[0] == manual
    assert sel.used[1] == dup
    assert defaults / "d00.png" not in sel.used  # deduped by content
    assert len(sel.used) == 15
    assert len(sel.dropped) == 21 - 15
    assert sel.warnings


def test_session_versions_chain_and_resolve(tmp_path):
    sessions = tmp_path / "sessions"
    s = Session.create(sessions, "No Damage Run", source={"kind": "refs-only", "base": None},
                       brief="b", game="Sifu", use_default_refs=True)
    assert s.name.endswith("no-damage-run")
    for vid, parent in (("v1", None), ("v2", "v1"), ("v3", "v2"), ("v4", "v2")):
        assert s.next_version_id() == vid
        s.add_version({"id": vid, "parent": parent, "kind": "ai", "instruction": vid, "model": "m",
                       "quality": "low", "provider": "p", "created_at": "t", "refs": []})
    assert [v["id"] for v in s.chain("v4")] == ["v1", "v2", "v4"]
    assert s.version("3")["id"] == "v3"
    assert resolve_session(sessions, "latest").name == s.name
    assert resolve_session(sessions, "damage").name == s.name
    assert (s.path / "prompts.md").read_text(encoding="utf-8").count("## v") == 4


def test_session_add_and_drop_refs(tmp_path):
    s = Session.create(tmp_path, "x", source={"kind": "refs-only", "base": None},
                       brief="b", game="Sifu", use_default_refs=True)
    a = _img(tmp_path / "a.png", color=(1, 1, 1))
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    a_same_name = _img(other_dir / "a.png", color=(2, 2, 2))
    added = s.add_refs([a, a, a_same_name])
    assert added == ["refs/a.png", "refs/a_2.png"]
    s.drop_refs(["a_2.png"])
    assert [p.name for p in s.ref_paths()] == ["a.png"]
    with pytest.raises(ThumbgenError):
        s.drop_refs(["missing.png"])


def test_overlay_logo_trims_and_positions():
    from ai_thumbgen.logo_overlay import overlay_logo

    bg = Image.new("RGB", (1000, 500), (0, 0, 0))
    logo = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    logo.paste((255, 0, 0, 255), (100, 100, 200, 150))  # visible 100x50 inside transparent padding
    out = overlay_logo(bg, logo, pos="bottom-left", width=0.2, margin=0.0)
    # Visible part scaled to 200x100, flush with the bottom-left corner.
    assert out.getpixel((5, 495)) == (255, 0, 0)
    assert out.getpixel((195, 405)) == (255, 0, 0)
    assert out.getpixel((205, 495)) == (0, 0, 0)
    assert out.getpixel((5, 395)) == (0, 0, 0)

    with pytest.raises(ThumbgenError):
        overlay_logo(bg, Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
