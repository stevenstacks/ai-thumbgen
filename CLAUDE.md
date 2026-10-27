# ai-thumbgen: notes for Claude Code

CLI thumbnail generator: gameplay video/screenshot -> base frame -> OpenAI image edit, versioned iterations.
Formats: `--format youtube` (16:9, default) and `--format tiktok` (9:16 cover, text/logos kept in the central 3:4).
Python package in `src/ai_thumbgen`, run as `ai-thumbgen` from the project venv
(Windows: `.\.venv\Scripts\ai-thumbgen.exe`, macOS/Linux: `.venv/bin/ai-thumbgen`).
Personal setup (language, game, recording format, logo paths) lives in `CLAUDE.local.md` (gitignored), if present.
Reply in the user's language; always write prompts for the image model in English.

## Hard rules
- NEVER read, print or edit `.env` (it holds OPENAI_API_KEY). If the key is missing, tell the user to copy
  `.env.example` to `.env` and fill it in themselves in an editor. Never ask them to paste it.
- Use the real gameplay screenshot as the base; never ask the model to redraw the character from scratch.
- Every API call costs money. Use `--dry-run` when unsure; default quality is `medium` while iterating,
  suggest `--quality high` only for the final version.
- Always pass `--json` and parse the output (`ok`, `version`, `image`, `upload`, `warnings`, `error`).

## Mapping plain requests to commands
| User says | Run |
|---|---|
| "find a good moment between 10 and 15 min" | `ai-thumbgen frames -v VIDEO --from 10:00 --to 15:00 --every 10s --json`, then Read the sheet JPG and suggest timestamps |
| "grab the frame at 12:34" | `ai-thumbgen frame -v VIDEO --at 12:34 --json` (add `--crop-x 0.3` if the character is left of center) |
| "new thumbnail from video ... at 12:34, text NO DAMAGE" | `ai-thumbgen new -v VIDEO --at 12:34 -p "<english brief>" --json` |
| "make a TikTok cover / thumbnail tiktok" | add `--format tiktok` to `frame`/`frames`/`new`; preview the crop with `frame --format tiktok` first and adjust `--crop-x` |
| non-game footage (OOTD, vlog, real people) | add `--about "<what the frame shows>"` to `new` and usually `--no-default-refs`; the prompt then stops calling it a gameplay screenshot |
| "use this screenshot" | `ai-thumbgen new -i IMAGE -p "..." --json` |
| "just build it from these references" | `ai-thumbgen new -r A -r B [--no-default-refs] -p "..." --json` (refs-only mode) |
| "bigger text" / "less glow" / "move the character left" | `ai-thumbgen edit latest -p "<one precise English change>" --json` |
| "go back to v2, then ..." | `ai-thumbgen edit latest --from v2 -p "..." --json` |
| "add this reference" | `ai-thumbgen edit latest -r PATH -p "..." --json` (ref is kept for the rest of the session) |
| "don't use the default references" | add `--no-default-refs` (this run only) |
| "use the Elden Ring style" / "which reference sets are there?" | `--ref-set eldenring` on `new` (or `edit`, kept for the session) / `ai-thumbgen refs --json` |
| "fewer references, cheaper" | `--max-refs 4` on `new`/`edit` (kept for the session) |
| "the AI text is bad, draw it manually" | `ai-thumbgen text latest --text "NO DAMAGE" --pos top-left --glow "#ff2020" --json` |
| "paste this logo as is" / "logo top-right" | `ai-thumbgen logo latest --image PATH --pos top-right --width 0.3 --json` (no API call; pixel-exact) |
| "make the logo smaller / move it" | `ai-thumbgen logo latest --from vN --image PATH --pos ... --width ... --json` (vN = the version before the logo) |
| "use the sunburst model / high quality" | add `-m gpt-image-2.5-sunburst` / `-q high` |
| "show sessions" / "history" | `ai-thumbgen list --json` / `ai-thumbgen show latest --json` |

Writing edit prompts: describe ONE change concretely ("Make the title text 'NO DAMAGE' about 30% larger,
keep its position and font"), and do not repeat the whole brief; the CLI adds the brief and change history.

Chained AI edits degrade people (faded skin, altered pose). If a person starts looking worse, branch from the best
early version with `--from vN` and put all accepted changes in one prompt; say explicitly to keep the person
identical. Precise partial occlusion ("only 1/3 of the letter behind her hair") is not reliable with the model;
after 1-2 misses, stop spending and offer a non-AI fix.

Logos that must look exactly right: do NOT send them to the model as refs (it redraws them). In the brief, ask
to keep that corner clear ("leave the top-right area dark and empty for a logo"), then paste with `ai-thumbgen logo`.
Do AI edits on the version before the logo, then re-run `logo`, so the model never redraws the logo.

After each `new`/`edit`/`text`/`logo`: Read the `upload` JPG to look at the result, describe briefly what changed
and anything off (misspelled text, altered face), then suggest the next step.

## Layout
- `output/sessions/<date>_<slug>/`: `session.json` (source, format, brief, refs, version tree), `base.png`,
  `refs/`, `vN.png` (archive), `vN_<w>x<h>.jpg` uploads (<2MB; YouTube 1280x720, TikTok 1080x1920 + 1080x1440),
  `prompts.md` (log). The JSON `uploads` field lists every upload file; for TikTok, Read both.
- Formats live in `FORMATS` in `config.py` (API size, upload sizes, safe area, prompt note); add new ones there.
- `references/`: style refs. Top level = default set; each subfolder is a reference set chosen with `--ref-set`
  (default from `THUMBGEN_REFS`), stored per session. Max 16 images per request (target + 15 refs), `--max-refs` caps it.
- `assets/`: logos for `ai-thumbgen logo`; never sent to the model. Never put logos in `references/`.
- `references/`, `assets/`, `fonts/` and `output/` are gitignored.
- Providers: `src/ai_thumbgen/providers/`. Add a new one by implementing `ImageProvider` and registering it in `PROVIDERS`.
- Tests: `pytest` (no API calls; fake provider).
