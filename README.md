# ai-thumbgen

A command-line tool that turns gameplay footage into YouTube thumbnails and TikTok covers with OpenAI's
image models.

Pick a moment from your recording, and `ai-thumbgen` grabs the frame, crops it to 16:9 (ultrawide is fine),
and asks the model to *edit* that real screenshot into a thumbnail, so your character, face and scene stay
yours instead of being redrawn from scratch. Every change becomes a new version you can branch from,
compare and roll back to.

## Features
- **Frame picking from long videos**: contact sheets with timestamps and single-frame grabs via ffmpeg
  (HEVC and HDR handled). Free, no API calls.
- **AI edits on the real frame**: `gpt-image-2` / `gpt-image-2.5-*` through the OpenAI Images API, with
  optional style references from your channel.
- **Versioned iterations**: `edit` one change at a time, branch from any version (`--from v2`); the
  brief and change history are re-sent automatically, because the API is stateless.
- **Pixel-exact overlays**: paste a logo (`logo`) or draw text (`text`) with Pillow when it has to be
  exact. Free.
- **YouTube and TikTok formats**: `--format youtube` (16:9) or `--format tiktok` (9:16 cover that keeps
  text, logos and faces inside the 3:4 area TikTok crops to in the profile grid).
- **Upload-ready output**: a PNG archive plus JPGs under 2 MB: 1280x720 for YouTube; 1080x1920 and a
  1080x1440 (3:4) crop for TikTok.
- **Agent-friendly**: every command supports `--json`; `new` and `edit` support `--dry-run`.

## Requirements
- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on `PATH` (only for grabbing frames from video)
- An OpenAI API key with access to the image models (organization verification may be required)

## Setup
```bash
git clone https://github.com/stevenstacks/ai-thumbgen.git
cd ai-thumbgen
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1   macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # Windows: Copy-Item .env.example .env
```
Open `.env` in an editor and set `OPENAI_API_KEY`. Optionally set `THUMBGEN_GAME` (e.g. `Elden Ring`) so
prompts name your game.

Optional folders (all gitignored, so your media stays local):
- `references/`: style examples (old thumbnails you like). One subfolder per project is a *reference set*:
  ```
  references/
    sifu/         style refs for one game or series
    eldenring/    ...for another
  ```
  Pick one with `--ref-set sifu` (or `THUMBGEN_REFS=sifu` in `.env`); images at the top level of
  `references/` are used when no set is chosen. Every reference is an extra input image on every
  `new`/`edit` call, so 3-6 consistent images work better (and cost less) than many; cap them with
  `--max-refs`.
- `assets/`: logos and other images to paste exactly with `logo`. Never sent to the model.
- `fonts/`: a `.ttf`/`.otf` font for `text` overlays (default: Impact/Arial Bold, else Pillow's font).

## Usage
```bash
# find a moment (free)
ai-thumbgen frames -v gameplay.mkv --from 10:00 --to 15:00 --every 10s
ai-thumbgen frame  -v gameplay.mkv --at 12:34.5 --crop-x 0.4

# start a session: from a video frame, a screenshot, or references only
ai-thumbgen new -v gameplay.mkv --at 12:34.5 -p "Big 'NO DAMAGE' text top-left, red glow, dramatic rim light"
ai-thumbgen new -i screenshot.png -p "..." -r extra_ref.png --no-default-refs
ai-thumbgen new -r shot1.png -r shot2.png -p "..."
ai-thumbgen new -v gameplay.mkv --at 12:34.5 --ref-set sifu --max-refs 4 -p "..."

# iterate, one change at a time
ai-thumbgen edit latest -p "Make the title text about 30% bigger"
ai-thumbgen edit latest --from v2 -p "Reduce the red glow" -q high -m gpt-image-2.5-sunburst

# exact overlays (free)
ai-thumbgen text latest --text "NO DAMAGE" --pos top-left --glow "#ff2020"
ai-thumbgen logo latest --image assets/my-logo.png --pos top-right --width 0.3 --shadow "#000000"

# TikTok cover (9:16); preview the crop first, then generate
ai-thumbgen frame -v gameplay.mkv --at 12:34.5 --format tiktok --crop-x 0.4
ai-thumbgen new   -v gameplay.mkv --at 12:34.5 --format tiktok -p "..."

# not gameplay? describe what the frame shows so the prompt does not call it a game screenshot
ai-thumbgen new -v ootd.mp4 --at 0:08 --format tiktok --no-default-refs   --about "a real phone video frame of a woman showing her outfit" -p "Aesthetic cover, title 'Spill The Fit'"

# history and reference sets
ai-thumbgen refs
ai-thumbgen list
ai-thumbgen show latest
ai-thumbgen open latest v3
```

Tip for people: every AI edit re-renders the whole image, so faces and skin slowly lose quality over a
chain of edits. When that happens, branch from an early good version (`edit --from v1`) and ask for all the
changes in one prompt instead of stacking more edits.

Tip for logos: image models redraw everything they see, so a logo sent as a reference never comes back
exact. Keep logos in `assets/`, not `references/`. Ask for an empty corner in the brief ("leave the top-right area dark and empty for a logo"), then
paste it with `logo`.

## Output
```
output/sessions/<date>_<slug>/
  session.json         source, format, brief, reference set, references, version tree
  base.png             base frame at the API size
  v1.png, v2.png ...   archive (2048x1152 for YouTube, 1152x2048 for TikTok)
  v1_1280x720.jpg      YouTube upload (< 2 MB)
  v1_1080x1920.jpg     TikTok cover, full 9:16
  v1_1080x1440.jpg     TikTok cover, 3:4 crop (what the desktop cover upload asks for)
  prompts.md           every prompt that was sent
```
The format is chosen in `new` and kept for the whole session; `edit`, `text` and `logo` follow it.
TikTok only accepts custom cover images from the desktop/web uploader; the mobile app picks a video frame.

## Using it with Claude Code
The repo includes a `CLAUDE.md` that teaches [Claude Code](https://claude.com/claude-code) to drive the CLI
from plain requests ("make the text bigger", "go back to v2"), look at each result and suggest the next
step. It also blocks the agent from reading `.env`. Claude Code is optional: the CLI works on its own.

## Notes on the API
- Endpoint: `images.edit`, up to 16 input images per request (target + 15 references), each < 50 MB.
- Output size 2048x1152 or 1152x2048 (multiples of 16, below the experimental range above 2560x1440 pixels).
- `input_fidelity` is not sent: `gpt-image-2` does not accept it.
- Costs: each `new`/`edit` is one paid call; `frame`, `frames`, `text`, `logo` and `--dry-run` are free.

## Development
```bash
pytest   # no API calls; uses a fake provider
```
New image backends: implement `ImageProvider` in `src/ai_thumbgen/providers/` and register it in `PROVIDERS`.

## License
[MIT](LICENSE)
