# ai-thumbgen: notes for Claude Code

CLI YouTube thumbnail generator: gameplay video/screenshot -> 16:9 base -> OpenAI image edit, versioned iterations.
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
| "use this screenshot" | `ai-thumbgen new -i IMAGE -p "..." --json` |
| "just build it from these references" | `ai-thumbgen new -r A -r B [--no-default-refs] -p "..." --json` (refs-only mode) |
| "bigger text" / "less glow" / "move the character left" | `ai-thumbgen edit latest -p "<one precise English change>" --json` |
| "go back to v2, then ..." | `ai-thumbgen edit latest --from v2 -p "..." --json` |
| "add this reference" | `ai-thumbgen edit latest -r PATH -p "..." --json` (ref is kept for the rest of the session) |
| "don't use the default references" | add `--no-default-refs` (this run only) |
| "the AI text is bad, draw it manually" | `ai-thumbgen text latest --text "NO DAMAGE" --pos top-left --glow "#ff2020" --json` |
| "paste this logo as is" / "logo top-right" | `ai-thumbgen logo latest --image PATH --pos top-right --width 0.3 --json` (no API call; pixel-exact) |
| "make the logo smaller / move it" | `ai-thumbgen logo latest --from vN --image PATH --pos ... --width ... --json` (vN = the version before the logo) |
| "use the sunburst model / high quality" | add `-m gpt-image-2.5-sunburst` / `-q high` |
| "show sessions" / "history" | `ai-thumbgen list --json` / `ai-thumbgen show latest --json` |

Writing edit prompts: describe ONE change concretely ("Make the title text 'NO DAMAGE' about 30% larger,
keep its position and font"), and do not repeat the whole brief; the CLI adds the brief and change history.

Logos that must look exactly right: do NOT send them to the model as refs (it redraws them). In the brief, ask
to keep that corner clear ("leave the top-right area dark and empty for a logo"), then paste with `ai-thumbgen logo`.
Do AI edits on the version before the logo, then re-run `logo`, so the model never redraws the logo.

After each `new`/`edit`/`text`/`logo`: Read the `upload` JPG to look at the result, describe briefly what changed
and anything off (misspelled text, altered face), then suggest the next step.

## Layout
- `output/sessions/<date>_<slug>/`: `session.json` (source, brief, refs, version tree), `base.png`,
  `refs/`, `vN.png` (2048x1152 archive), `vN_1280x720.jpg` (upload, <2MB), `prompts.md` (log).
- `references/`: default channel-style refs (top level only; subfolders are not auto-loaded).
  Max 16 images per request (target + 15 refs). `references/`, `fonts/` and `output/` are gitignored.
- Providers: `src/ai_thumbgen/providers/`. Add a new one by implementing `ImageProvider` and registering it in `PROVIDERS`.
- Tests: `pytest` (no API calls; fake provider).
