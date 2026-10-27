from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_FORMAT, Format, get_format
from .errors import ThumbgenError
from .imaging import file_sha1

SESSION_FILE = "session.json"
PROMPT_LOG = "prompts.md"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "thumbnail"


def normalize_version_id(vid: str) -> str:
    vid = vid.strip().lower()
    return vid if vid.startswith("v") else f"v{vid}"


class Session:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    # ---- lifecycle -------------------------------------------------------
    @classmethod
    def create(
        cls,
        sessions_dir: Path,
        name: str,
        *,
        source: dict,
        brief: str,
        game: str,
        use_default_refs: bool,
        fmt: str = DEFAULT_FORMAT,
        ref_set: str = "",
        max_refs: int | None = None,
        about: str = "",
        persist: bool = True,
    ) -> "Session":
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = sessions_dir / f"{stamp}_{slugify(name)}"
        i = 2
        while path.exists():  # same name within the same second
            path = sessions_dir / f"{stamp}_{slugify(name)}-{i}"
            i += 1
        data = {
            "name": path.name,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "game": game,
            "about": about,
            "format": get_format(fmt).name,
            "source": source,
            "brief": brief,
            "use_default_refs": use_default_refs,
            "ref_set": ref_set,
            "max_refs": max_refs,
            "session_refs": [],
            "versions": [],
        }
        session = cls(path, data)
        if persist:
            path.mkdir(parents=True, exist_ok=False)
            session.save()
        return session

    @classmethod
    def load(cls, path: Path) -> "Session":
        file = path / SESSION_FILE
        if not file.is_file():
            raise ThumbgenError(f"Not a session folder: {path}")
        return cls(path, json.loads(file.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.data["updated_at"] = now_iso()
        (self.path / SESSION_FILE).write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- accessors -------------------------------------------------------
    @property
    def name(self) -> str:
        return self.path.name

    @property
    def versions(self) -> list[dict]:
        return self.data["versions"]

    @property
    def latest(self) -> dict | None:
        return self.versions[-1] if self.versions else None

    @property
    def format(self) -> Format:
        return get_format(self.data.get("format"))  # sessions from before formats existed are YouTube

    @property
    def about(self) -> str:
        return self.data.get("about", "")

    @property
    def ref_set(self) -> str:
        return self.data.get("ref_set", "")  # older sessions used the top level of references/

    @property
    def max_refs(self) -> int | None:
        return self.data.get("max_refs")

    @property
    def base_path(self) -> Path | None:
        base = self.data["source"].get("base")
        return self.path / base if base else None

    def next_version_id(self) -> str:
        return f"v{len(self.versions) + 1}"

    def version(self, vid: str) -> dict:
        vid = normalize_version_id(vid)
        for v in self.versions:
            if v["id"] == vid:
                return v
        known = ", ".join(v["id"] for v in self.versions) or "none"
        raise ThumbgenError(f"Version {vid} not found in {self.name} (versions: {known})")

    def chain(self, vid: str) -> list[dict]:
        """Versions from the root to `vid`, following parent links."""
        out: list[dict] = []
        current: dict | None = self.version(vid)
        while current:
            out.append(current)
            current = self.version(current["parent"]) if current.get("parent") else None
        return list(reversed(out))

    def file(self, rel: str) -> Path:
        return self.path / rel

    def ref_paths(self) -> list[Path]:
        return [self.path / r for r in self.data["session_refs"]]

    # ---- mutations -------------------------------------------------------
    def add_refs(self, sources: list[Path]) -> list[str]:
        """Copy refs into refs/ (skipping content duplicates). Returns the newly added relative paths."""
        refs_dir = self.path / "refs"
        refs_dir.mkdir(exist_ok=True)
        existing = {file_sha1(p) for p in self.ref_paths()}
        added: list[str] = []
        for src in sources:
            digest = file_sha1(src)
            if digest in existing:
                continue
            dest = refs_dir / src.name
            i = 2
            while dest.exists():
                dest = refs_dir / f"{src.stem}_{i}{src.suffix}"
                i += 1
            shutil.copy2(src, dest)
            rel = dest.relative_to(self.path).as_posix()
            self.data["session_refs"].append(rel)
            existing.add(digest)
            added.append(rel)
        return added

    def drop_refs(self, names: list[str]) -> list[str]:
        removed = []
        for name in names:
            matches = [r for r in self.data["session_refs"] if Path(r).name == name or r == name]
            if not matches:
                raise ThumbgenError(
                    f"Session ref '{name}' not found. Session refs: "
                    + (", ".join(Path(r).name for r in self.data["session_refs"]) or "none")
                )
            for r in matches:
                self.data["session_refs"].remove(r)
                removed.append(r)
        return removed

    def add_version(self, entry: dict) -> None:
        self.versions.append(entry)
        self.save()
        self._append_prompt_log(entry)

    def _append_prompt_log(self, v: dict) -> None:
        header = f"## {v['id']}  ·  parent: {v.get('parent') or '-'}  ·  {v['kind']}"
        if v["kind"] == "ai":
            header += f"  ·  {v['provider']}/{v['model']}/{v['quality']}"
        lines = [header, "", f"- created: {v['created_at']}", f"- instruction: {v['instruction']}"]
        if v.get("refs") is not None:
            lines.append(f"- references ({len(v['refs'])}): " + (", ".join(Path(r).name for r in v["refs"]) or "none"))
        if v.get("usage"):
            lines.append(f"- usage: {json.dumps(v['usage'])}")
        if v.get("full_prompt"):
            lines += ["", "<details><summary>full prompt</summary>", "", "```text", v["full_prompt"], "```", "</details>"]
        if v.get("text_overlay"):
            lines.append(f"- overlay: {json.dumps(v['text_overlay'], ensure_ascii=False)}")
        with open(self.path / PROMPT_LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")


def list_sessions(sessions_dir: Path) -> list[Session]:
    if not sessions_dir.is_dir():
        return []
    sessions = [Session.load(p) for p in sessions_dir.iterdir() if (p / SESSION_FILE).is_file()]
    # updated_at has one-second resolution; the file's mtime breaks ties between sessions saved in the same second.
    return sorted(sessions, key=lambda s: (s.data.get("updated_at", ""), (s.path / SESSION_FILE).stat().st_mtime_ns))


def resolve_session(sessions_dir: Path, key: str) -> Session:
    """`latest` (most recently updated), exact folder name, unique prefix, or unique substring."""
    sessions = list_sessions(sessions_dir)
    if not sessions:
        raise ThumbgenError("No sessions yet. Create one with `ai-thumbgen new`.")
    if key == "latest":
        return sessions[-1]
    for test in (lambda n: n == key, lambda n: n.startswith(key), lambda n: key.lower() in n.lower()):
        matches = [s for s in sessions if test(s.name)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ThumbgenError(f"'{key}' matches several sessions: " + ", ".join(s.name for s in matches))
    raise ThumbgenError(f"No session matches '{key}'. Run `ai-thumbgen list`.")
