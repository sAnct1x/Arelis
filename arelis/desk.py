"""The desk: pages and artifacts that exist because you talked.

Workspace roots are the sandbox — the legal boundary. The desk is the
inbox that sits on top of it: notes you asked to keep, files she wrote,
plots, pictures. Pins stay at the top. A missing file drops off the list
rather than becoming a dead row.

Persisted as JSON under the records folder so the UI and the core process
share one pile without holding the same object.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.paths import state_dir
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

_DESK_FILE = "desk.json"
_NOTE_LIMIT = 8000
_TITLE_LIMIT = 48
_SLUG_LIMIT = 40
_LIST_LIMIT = 80
_MADE_SOURCES = frozenset({"keep", "workspace", "document", "plot", "image", "save", "pin"})
_JUNK_DIR_NAMES = frozenset(
    {
        "tool_cache",
        "__pycache__",
        ".git",
        ".pytest_cache",
        "node_modules",
        ".venv",
        "venv",
    }
)

_KEEP_SLASH = re.compile(r"(?is)^/keep(?:\s+|$)(.*)$")
_KEEP_NOTE = re.compile(
    r"(?ix)^"
    r"(?:hey\s+arelis,?\s+)?"
    r"(?:please\s+)?"
    r"(?:"
    r"keep(?:\s+this)?|"
    r"jot\s+this\s+down|"
    r"note\s+this|"
    r"put\s+this\s+on\s+the\s+desk"
    r")"
    r"(?:\s+for\s+later)?"
    r"\s*[:\u2014\u2013\-]\s*"
    r"(.+)"
    r"$"
)
_KEEP_LAST = re.compile(
    r"(?ix)^"
    r"(?:hey\s+arelis,?\s+)?"
    r"(?:please\s+)?"
    r"(?:"
    r"keep\s+this|"
    r"keep\s+that|"
    r"pin\s+this|"
    r"pin\s+that|"
    r"put\s+(?:this|that)\s+on\s+the\s+desk"
    r")"
    r"[.!]?"
    r"$"
)

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_DOC_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx", ".csv"})
_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".py",
        ".pyw",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".tsv",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".xml",
        ".ini",
        ".cfg",
        ".log",
    }
)


@dataclass
class Artifact:
    abs_path: str
    label: str
    kind: str = "file"
    source: str = "open"
    root_name: str = ""
    room_id: str = ""
    created_at: str = ""
    last_seen: str = ""
    pinned: bool = False

    def exists(self) -> bool:
        try:
            return Path(self.abs_path).is_file()
        except OSError:
            return False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeskStore:
    """JSON pile of desk artifacts. One file, last write wins."""

    path: Path = field(default_factory=lambda: state_dir() / _DESK_FILE)
    _items: list[Artifact] = field(default_factory=list)
    _loaded: bool = False

    def _ensure(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        raw = _read_json(self.path)
        items = raw.get("artifacts") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return
        for row in items:
            if not isinstance(row, dict):
                continue
            abs_path = str(row.get("abs_path") or "").strip()
            if not abs_path:
                continue
            self._items.append(
                Artifact(
                    abs_path=abs_path,
                    label=str(row.get("label") or Path(abs_path).name),
                    kind=str(row.get("kind") or "file"),
                    source=str(row.get("source") or "open"),
                    root_name=str(row.get("root_name") or ""),
                    room_id=str(row.get("room_id") or ""),
                    created_at=str(row.get("created_at") or ""),
                    last_seen=str(row.get("last_seen") or ""),
                    pinned=bool(row.get("pinned")),
                )
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "artifacts": [item.as_dict() for item in self._items],
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def record(
        self,
        abs_path: str,
        *,
        label: str = "",
        kind: str = "",
        source: str = "open",
        root_name: str = "",
        room_id: str = "",
        pin: bool = False,
    ) -> Artifact | None:
        """Add or refresh one file. Opening a file does not invent a desk row.

        Recents are a click log. The desk is papers you kept or she made.
        source=open only updates a row that is already here.
        """
        self._ensure()
        target = _normalize_abs(abs_path)
        if not target or is_desk_junk(target):
            return None
        now = _now()
        kind = (kind or infer_kind(target, source=source)).strip() or "file"
        label = (label or Path(target).name).strip() or Path(target).name
        for item in self._items:
            if item.abs_path == target:
                item.label = label
                item.kind = kind
                item.source = source or item.source
                if root_name:
                    item.root_name = root_name
                if room_id:
                    item.room_id = room_id
                item.last_seen = now
                if pin:
                    item.pinned = True
                self._save()
                return item
        if source not in _MADE_SOURCES and not pin:
            return None
        item = Artifact(
            abs_path=target,
            label=label,
            kind=kind,
            source=source or "open",
            root_name=root_name,
            room_id=room_id,
            created_at=now,
            last_seen=now,
            pinned=pin,
        )
        self._items.append(item)
        self._save()
        return item

    def pin(self, abs_path: str, *, pinned: bool = True) -> Artifact | None:
        self._ensure()
        target = _normalize_abs(abs_path)
        if not target:
            return None
        for item in self._items:
            if item.abs_path == target:
                item.pinned = pinned
                item.last_seen = _now()
                self._save()
                return item
        if not pinned:
            return None
        item = self.record(target, source="pin", pin=True)
        return item

    def drop(self, abs_path: str) -> bool:
        """Take a file off the desk. The file on disk stays."""
        self._ensure()
        target = _normalize_abs(abs_path)
        if not target:
            return False
        before = len(self._items)
        self._items = [item for item in self._items if item.abs_path != target]
        if len(self._items) == before:
            return False
        self._save()
        return True

    def list_for(
        self,
        *,
        root_name: str = "",
        room_id: str = "",
        include_orbit: bool = True,
        limit: int = _LIST_LIMIT,
    ) -> list[Artifact]:
        """Pins first, then newest last_seen. Gone files are dropped."""
        self._ensure()
        kept: list[Artifact] = []
        lost = False
        for item in self._items:
            if not item.exists() or is_desk_junk(item.abs_path):
                lost = True
                continue
            kept.append(item)
        if lost:
            self._items = kept
            self._save()
        visible: list[Artifact] = []
        for item in kept:
            if root_name:
                if item.root_name == root_name:
                    visible.append(item)
                elif include_orbit and not item.root_name and not room_id:
                    visible.append(item)
                continue
            visible.append(item)
        pinned = [item for item in visible if item.pinned]
        rest = [item for item in visible if not item.pinned]
        pinned.sort(key=lambda a: a.last_seen, reverse=True)
        rest.sort(key=lambda a: a.last_seen, reverse=True)
        return (pinned + rest)[: max(1, limit)]


def is_desk_junk(path: str | Path) -> bool:
    """Caches, VCS, and drop staging are not papers."""
    try:
        parts = {p.casefold() for p in Path(path).resolve().parts}
    except OSError:
        parts = {p.casefold() for p in Path(path).parts}
    if parts & {n.casefold() for n in _JUNK_DIR_NAMES}:
        return True
    return "drops" in parts and "data" in parts


def infer_kind(path: str | Path, *, source: str = "") -> str:
    src = (source or "").strip().lower()
    if src == "keep":
        return "note"
    if src in {"plot", "image", "document"}:
        return src
    suffix = Path(path).suffix.lower()
    name = Path(path).name.lower()
    parent = Path(path).parent.name.lower()
    if src == "workspace" and parent == "notes" and suffix == ".md":
        return "note"
    if parent == "notes" and suffix == ".md":
        return "note"
    if parent == "plots" and suffix in _IMAGE_SUFFIXES:
        return "plot"
    if name.startswith("plot-") and suffix in _IMAGE_SUFFIXES:
        return "plot"
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _DOC_SUFFIXES:
        return "document"
    if suffix in _TEXT_SUFFIXES:
        return "file"
    return "file"


def is_text_kind(kind: str, path: str = "") -> bool:
    if kind in {"note", "file"}:
        suffix = Path(path).suffix.lower()
        return not suffix or suffix in _TEXT_SUFFIXES or suffix == ".md"
    suffix = Path(path).suffix.lower()
    return suffix in _TEXT_SUFFIXES


def is_image_kind(kind: str, path: str = "") -> bool:
    if kind in {"image", "plot"}:
        return True
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES


def match_keep_note(text: str) -> str | None:
    """Body of a 'keep this: …' / `/keep …` ask, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    slash = _KEEP_SLASH.match(raw)
    if slash:
        body = slash.group(1).strip()
        return body or None
    hit = _KEEP_NOTE.match(raw)
    if hit:
        body = hit.group(1).strip()
        return body or None
    return None


def match_keep_last(text: str) -> bool:
    """True for a bare 'keep this' / 'pin that' with no note body."""
    raw = (text or "").strip()
    if not raw or match_keep_note(raw):
        return False
    return bool(_KEEP_LAST.match(raw))


def note_title(text: str) -> str:
    line = " ".join((text or "").strip().split())
    if not line:
        return "note"
    cut = line.split(".")[0].strip() or line
    if len(cut) > _TITLE_LIMIT:
        cut = cut[: _TITLE_LIMIT - 1].rstrip() + "…"
    return cut


def write_note(
    workspace: WorkspaceRoots,
    text: str,
    *,
    title: str = "",
    room_id: str = "",
    store: DeskStore | None = None,
) -> Artifact:
    """Write a markdown note under the active project's notes/ folder."""
    body = (text or "").strip()
    if not body:
        raise ValueError("keep needs something to write down.")
    if len(body) > _NOTE_LIMIT:
        raise ValueError(
            f"That note is too long ({len(body)} characters). "
            f"Keep it under {_NOTE_LIMIT}."
        )
    heading = (title or "").strip() or note_title(body)
    entry = workspace.active_root()
    if entry.read_only:
        raise PermissionError(
            f"Workspace root `{entry.name}` is read-only; cannot keep a note there."
        )
    folder = entry.path / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    slug = _slug(heading)
    path = folder / f"{day}-{slug}.md"
    n = 2
    while path.exists():
        path = folder / f"{day}-{slug}-{n}.md"
        n += 1
    when = datetime.now().strftime("%d %B %Y").lstrip("0")
    page = f"# {heading}\n\n{body}\n\nKept {when}.\n"
    path.write_text(page, encoding="utf-8")
    desk = store or DeskStore()
    item = desk.record(
        str(path),
        label=heading,
        kind="note",
        source="keep",
        root_name=entry.name,
        room_id=room_id,
    )
    if item is None:
        raise OSError(f"Wrote {path} but could not put it on the desk.")
    return item


def _slug(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    cleaned = cleaned[:_SLUG_LIMIT].strip("-")
    return cleaned or "note"


def _normalize_abs(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).expanduser().resolve())
    except OSError:
        return ""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}
