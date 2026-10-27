import io
import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from ai_thumbgen import providers
from ai_thumbgen.cli import app
from ai_thumbgen.providers import EditResult

runner = CliRunner()


class FakeProvider:
    name = "fake"
    max_input_images = 16

    def __init__(self):
        self.requests = []

    def edit(self, request):
        self.requests.append(request)
        buf = io.BytesIO()
        Image.new("RGB", (1536, 1024), (30, 30, 30)).save(buf, "PNG")  # not 16:9 on purpose
        return EditResult(image_bytes=buf.getvalue(), usage={"total_tokens": 1})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("THUMBGEN_ROOT", str(tmp_path))
    monkeypatch.setenv("THUMBGEN_MODEL", "gpt-image-2")
    monkeypatch.setenv("THUMBGEN_QUALITY", "medium")
    fake = FakeProvider()
    monkeypatch.setitem(providers.PROVIDERS, "fake", lambda: fake)
    (tmp_path / "references").mkdir()
    Image.new("RGB", (100, 100), (200, 0, 0)).save(tmp_path / "references" / "style1.png")
    shot = tmp_path / "shot.png"
    Image.new("RGB", (3440, 1440), (0, 120, 0)).save(shot)
    return tmp_path, fake, shot


def run(*args):
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_full_flow(env):
    root, fake, shot = env
    out = run("new", "--image", str(shot), "--prompt", "NO DAMAGE red glow", "--provider", "fake")
    assert out["version"] == "v1"
    with Image.open(out["image"]) as im:
        assert im.size == (2048, 1152)
    with Image.open(out["upload"]) as im:
        assert im.size == (1280, 720)
    req = fake.requests[-1]
    assert len(req.images) == 2  # base + 1 default ref
    assert req.size == (2048, 1152) and req.model == "gpt-image-2" and req.quality == "medium"

    extra = root / "extra.png"
    Image.new("RGB", (50, 50), (0, 0, 200)).save(extra)
    out2 = run("edit", "latest", "--prompt", "make the text bigger", "--ref", str(extra), "--provider", "fake",
               "-q", "low")
    assert out2["version"] == "v2" and out2["parent"] == "v1"
    assert len(fake.requests[-1].images) == 3
    assert fake.requests[-1].images[0].name == "v1.png"

    out3 = run("edit", "--from", "v1", "--prompt", "less glow", "--no-default-refs", "--provider", "fake")
    assert out3["parent"] == "v1"
    assert len(fake.requests[-1].images) == 2  # v1 + session ref only

    out4 = run("text", "--text", "NO DAMAGE", "--glow", "#ff2020")
    assert out4["version"] == "v4" and out4["parent"] == "v3"

    shown = run("show", "latest")
    assert [v["id"] for v in shown["versions"]] == ["v1", "v2", "v3", "v4"]
    prompt_v2 = shown["versions"][1]["full_prompt"]
    assert "make the text bigger" in prompt_v2 and "NO DAMAGE red glow" in prompt_v2
    assert "Changes already applied" not in fake.requests[-1].prompt  # v3 branches from v1: no history yet

    listed = run("list")
    assert listed["sessions"][0]["versions"] == 4


def test_refs_only_dry_run(env):
    root, fake, _ = env
    a = root / "a.png"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(a)
    out = run("new", "--ref", str(a), "--no-default-refs", "--prompt", "boss fight", "--dry-run")
    assert out["dry_run"] and out["source"]["kind"] == "refs-only"
    assert out["images"] == [str(a.resolve())]
    assert not (root / "output" / "sessions").exists()  # dry run writes nothing
    assert fake.requests == []


def test_refs_only_without_images_errors(env):
    result = runner.invoke(app, ["new", "--no-default-refs", "--prompt", "x", "--dry-run"])
    assert result.exit_code != 0


def test_reference_cap(env):
    root, fake, shot = env
    for i in range(20):
        Image.new("RGB", (10, 10), (i, 9, 9)).save(root / "references" / f"r{i:02d}.png")
    out = run("new", "--image", str(shot), "--prompt", "x", "--dry-run")
    assert len(out["images"]) == 16
    assert len(out["references_dropped"]) == 21 - 15
    assert out["warnings"]


def test_logo_overlay(env):
    root, fake, shot = env
    run("new", "--image", str(shot), "--prompt", "PART 1", "--provider", "fake")
    logo = root / "logo.png"
    Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(logo)
    out = run("logo", "--image", str(logo), "--pos", "top-right", "--width", "0.25", "--shadow", "#000000")
    assert out["version"] == "v2" and out["parent"] == "v1"
    with Image.open(out["image"]) as im:
        assert im.size == (2048, 1152)
        assert im.getpixel((2048 - 82 - 10, 46 + 10)) == (255, 255, 255)  # inside the logo
        assert im.getpixel((10, 1100))[0] < 100  # untouched background

    run("edit", "latest", "--prompt", "more contrast", "--provider", "fake")
    assert "A logo was pasted at top-right" in fake.requests[-1].prompt

    bad = runner.invoke(app, ["logo", "--image", str(logo), "--pos", "nowhere", "--json"])
    assert bad.exit_code != 0


def test_tiktok_format(env):
    root, fake, shot = env
    out = run("new", "--image", str(shot), "--prompt", "PART 1", "--format", "tiktok", "--provider", "fake")
    assert out["format"] == "tiktok"
    req = fake.requests[-1]
    assert req.size == (1152, 2048)
    assert "TikTok cover" in req.prompt and "3:4" in req.prompt
    with Image.open(req.images[0]) as im:
        assert im.size == (1152, 2048)  # base frame cropped to 9:16
    sizes = []
    for path in out["uploads"]:
        with Image.open(path) as im:
            sizes.append(im.size)
    assert sizes == [(1080, 1920), (1080, 1440)]

    logo = root / "logo.png"
    Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(logo)
    out2 = run("logo", "--image", str(logo), "--pos", "top-right", "--margin", "0")
    with Image.open(out2["image"]) as im:
        assert im.getpixel((1150, 300)) == (255, 255, 255)  # just inside the 3:4 area (starts at y=256)
        assert im.getpixel((1150, 250))[0] < 100  # top eighth stays clear

    out3 = run("text", "--text", "PART 1", "--pos", "bottom-left")
    assert out3["format"] == "tiktok"
    run("edit", "latest", "--prompt", "more glow", "--provider", "fake")
    assert fake.requests[-1].size == (1152, 2048) and "TikTok cover" in fake.requests[-1].prompt

    dry = run("new", "--image", str(shot), "--prompt", "x", "--format", "tiktok", "--dry-run")
    assert dry["size"] == "1152x2048"
    bad = runner.invoke(app, ["new", "--image", str(shot), "--prompt", "x", "--format", "insta", "--json"])
    assert bad.exit_code != 0


def test_reference_sets(env, monkeypatch):
    root, fake, shot = env
    sifu = root / "references" / "sifu"
    sifu.mkdir()
    for i in range(3):
        Image.new("RGB", (10, 10), (i, 50, 50)).save(sifu / f"s{i}.png")
    (root / "references" / "elden").mkdir()
    Image.new("RGB", (10, 10), (9, 9, 9)).save(root / "references" / "elden" / "e.png")

    listed = run("refs")
    assert {r["name"]: r["images"] for r in listed["ref_sets"]} == {"": 1, "elden": 1, "sifu": 3}

    out = run("new", "--image", str(shot), "--prompt", "x", "--ref-set", "sifu", "--max-refs", "2",
              "--provider", "fake")
    req = fake.requests[-1]
    assert [p.parent.name for p in req.images[1:]] == ["sifu", "sifu"]  # set only, capped at 2
    assert run("show", "latest")["ref_set"] == "sifu"

    run("edit", "latest", "--prompt", "y", "--provider", "fake")
    assert len(fake.requests[-1].images) == 3  # set and limit kept for the session
    run("edit", "latest", "--prompt", "z", "--ref-set", "elden", "--max-refs", "5", "--provider", "fake")
    assert [p.name for p in fake.requests[-1].images[1:]] == ["e.png"]

    monkeypatch.setenv("THUMBGEN_REFS", "sifu")
    dry = run("new", "--image", str(shot), "--prompt", "x", "--dry-run")
    assert dry["ref_set"] == "sifu" and len(dry["references_used"]) == 3

    for bad in ("nope", "../x"):
        result = runner.invoke(app, ["new", "--image", str(shot), "--prompt", "x", "--ref-set", bad, "--json"])
        assert result.exit_code != 0
    assert len(fake.requests) == 3 and out["version"] == "v1"


def test_about_replaces_gameplay_wording(env, monkeypatch):
    root, fake, shot = env
    monkeypatch.setenv("THUMBGEN_GAME", "Sifu")
    run("new", "--image", str(shot), "--prompt", "x", "--provider", "fake")
    assert "gameplay screenshot from the video game Sifu" in fake.requests[-1].prompt

    about = "a real phone video frame of a woman showing her outfit"
    run("new", "--image", str(shot), "--prompt", "x", "--about", about, "--provider", "fake")
    assert f"Image 1 is {about}." in fake.requests[-1].prompt
    assert "gameplay" not in fake.requests[-1].prompt and "Sifu" not in fake.requests[-1].prompt
    run("edit", "latest", "--prompt", "y", "--provider", "fake")
    assert f"made from {about}" in fake.requests[-1].prompt and "Sifu" not in fake.requests[-1].prompt


def test_invalid_model(env):
    result = runner.invoke(app, ["new", "--prompt", "x", "--model", "gpt-image-1", "--dry-run"])
    assert result.exit_code != 0
