from __future__ import annotations

THUMBNAIL_GOALS = (
    "Output: a 16:9 YouTube thumbnail. Bold, high contrast, readable at small sizes on a phone. "
    "Any text must be spelled exactly as given, large, clean and fully inside the frame."
)


def _game(game: str) -> str:
    return f"the video game {game}" if game else "a video game"


def _ref_line(first_ref_index: int, n_refs: int) -> str:
    if n_refs <= 0:
        return ""
    span = f"Image {first_ref_index}" if n_refs == 1 else f"Images {first_ref_index}-{first_ref_index + n_refs - 1}"
    return (
        f"{span}: style references from my channel. Borrow only their typography, color grading, "
        "lighting mood and graphic treatment. Do not copy their characters, scenes or text."
    )


def build_initial_prompt(game: str, brief: str, *, has_base: bool, n_refs: int) -> str:
    if has_base:
        lines = [
            f"Image 1 is a real gameplay screenshot from {_game(game)}. Turn it into a YouTube thumbnail "
            "by editing it. Keep the character, face, outfit, pose and environment from the screenshot; "
            "do not redraw, replace or restyle the character. Enhance lighting and add graphics/text around it.",
            _ref_line(2, n_refs),
        ]
    else:
        lines = [
            f"All images below are references. Images that are gameplay screenshots from {_game(game)} are the source "
            "for the character and scene: reuse them faithfully and do not invent a new character. "
            "Images that look like finished thumbnails are style references only (typography, color, layout).",
        ]
    lines += [THUMBNAIL_GOALS, f"Request: {brief}"]
    return "\n\n".join(line for line in lines if line)


def build_edit_prompt(game: str, brief: str, history: list[str], instruction: str, *, n_refs: int) -> str:
    lines = [
        f"Image 1 is the current version of a YouTube thumbnail for {_game(game)} that I am refining step by step. "
        "Apply ONLY the requested change below. Keep everything else identical: composition, character, "
        "pose, face, text content and spelling, colors and lighting.",
        _ref_line(2, n_refs),
        f"Original brief (for context): {brief}",
    ]
    if history:
        lines.append("Changes already applied (keep them):\n" + "\n".join(f"- {h}" for h in history))
    lines += [THUMBNAIL_GOALS, f"Requested change: {instruction}"]
    return "\n\n".join(line for line in lines if line)
