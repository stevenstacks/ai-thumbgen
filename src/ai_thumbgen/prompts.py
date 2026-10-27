from __future__ import annotations

from .config import Format


def _goals(fmt: Format) -> str:
    goals = (
        f"Output: a {fmt.label}. Bold, high contrast, readable at small sizes on a phone. "
        "Any text must be spelled exactly as given, large, clean and fully inside the frame."
    )
    return f"{goals} {fmt.prompt_note}" if fmt.prompt_note else goals


def _game(game: str) -> str:
    return f"the video game {game}" if game else "a video game"


def _source(game: str, about: str) -> str:
    return about if about else f"a real gameplay screenshot from {_game(game)}"


def _ref_line(first_ref_index: int, n_refs: int) -> str:
    if n_refs <= 0:
        return ""
    span = f"Image {first_ref_index}" if n_refs == 1 else f"Images {first_ref_index}-{first_ref_index + n_refs - 1}"
    return (
        f"{span}: style references from my channel. Borrow only their typography, color grading, "
        "lighting mood and graphic treatment. Do not copy their characters, scenes or text."
    )


def build_initial_prompt(
    game: str, brief: str, fmt: Format, *, has_base: bool, n_refs: int, about: str = ""
) -> str:
    if has_base:
        lines = [
            f"Image 1 is {_source(game, about)}. Turn it into a {fmt.noun} by editing it. "
            "Keep the person or character, face, body, outfit, pose and environment from the image; "
            "do not redraw, replace or restyle them. Enhance lighting and add graphics/text around them.",
            _ref_line(2, n_refs),
        ]
    else:
        lines = [
            f"All images below are references. Images that are {_source(game, about)} are the source "
            "for the person or character and scene: reuse them faithfully and do not invent a new character. "
            "Images that look like finished thumbnails or covers are style references only (typography, color, layout).",
        ]
    lines += [_goals(fmt), f"Request: {brief}"]
    return "\n\n".join(line for line in lines if line)


def build_edit_prompt(
    game: str, brief: str, fmt: Format, history: list[str], instruction: str, *, n_refs: int, about: str = ""
) -> str:
    subject = f"made from {about}" if about else f"for {_game(game)}"
    lines = [
        f"Image 1 is the current version of a {fmt.noun} {subject} that I am refining step by step. "
        "Apply ONLY the requested change below. Keep everything else identical: composition, person or "
        "character, pose, face, body, outfit, text content and spelling, colors and lighting.",
        _ref_line(2, n_refs),
        f"Original brief (for context): {brief}",
    ]
    if history:
        lines.append("Changes already applied (keep them):\n" + "\n".join(f"- {h}" for h in history))
    lines += [_goals(fmt), f"Requested change: {instruction}"]
    return "\n\n".join(line for line in lines if line)
