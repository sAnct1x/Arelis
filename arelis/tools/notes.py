"""Desk notes: the tool behind `keep this:` / `/keep`.

`write_note` in `arelis.desk` is the only store. add calls that. list / search /
read stay inside each workspace root's `notes/` folder — no walk, no drive
scan. Parent policy should treat add as a write:

    NOTES_WRITE_ACTIONS = frozenset({"add"})
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from arelis.desk import DeskStore, write_note
from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

# Parent policy.py: add this to the action_is_write table under "notes".
NOTES_WRITE_ACTIONS = frozenset({"add"})
WRITE_ACTIONS = NOTES_WRITE_ACTIONS

_NOTE_DIR = "notes"
_NOTE_SUFFIX = ".md"
_DATE_STEM = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-|$)")
_DEFAULT_LIMIT = 40
_MAX_LIMIT = 80
_SEARCH_DEFAULT = 20
_SEARCH_MAX = 50
_EXCERPT = 160
_READ_CHARS = 8000


class NotesTool:
    name = "notes"
    description = (
        "Desk notes under the active project's notes/ folder — the same "
        "pages 'keep this' / /keep already write. add needs text (optional "
        "title) and calls the existing desk writer; list titles, dates, and "
        "paths; search note bodies by keyword; read one note by id or path. "
        "Do not use memory remember for a page they want to reopen. "
        "add is a write; list/search/read are free."
    )
    # list/search/read dominate. Parent policy gates add via NOTES_WRITE_ACTIONS.
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "search", "read"],
                "description": (
                    "add writes a note (same as keep this), list the active "
                    "project's notes/, search bodies, or read one by id/path"
                ),
            },
            "text": {
                "type": "string",
                "description": "Note body for action=add (or use content/body)",
            },
            "content": {
                "type": "string",
                "description": "Alias for text on action=add",
            },
            "body": {
                "type": "string",
                "description": "Alias for text on action=add",
            },
            "title": {
                "type": "string",
                "description": "Optional short title for action=add",
            },
            "query": {
                "type": "string",
                "description": "Case-insensitive keywords for action=search",
            },
            "id": {
                "type": "string",
                "description": "Note id (filename stem) for action=read",
            },
            "path": {
                "type": "string",
                "description": "Note path or filename for action=read",
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"Max rows for list (default {_DEFAULT_LIMIT}, "
                    f"max {_MAX_LIMIT}) or search "
                    f"(default {_SEARCH_DEFAULT}, max {_SEARCH_MAX})"
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots | list[str],
        store: DeskStore | None = None,
    ) -> None:
        if isinstance(workspace, WorkspaceRoots):
            self.workspace = workspace
        else:
            self.workspace = WorkspaceRoots.from_paths(list(workspace))
        self.store = store

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "add":
            return self._add(kwargs)
        if action == "list":
            return self._list(kwargs)
        if action == "search":
            return self._search(kwargs)
        if action == "read":
            return self._read(kwargs)
        return ToolResult(
            ok=False,
            output="Unknown action. Use add, list, search, or read.",
        )

    def _add(self, kwargs: dict[str, Any]) -> ToolResult:
        body = str(
            kwargs.get("text")
            or kwargs.get("content")
            or kwargs.get("body")
            or kwargs.get("fact")
            or ""
        )
        title = str(kwargs.get("title") or "")
        try:
            item = write_note(self.workspace, body, title=title, store=self.store)
        except (ValueError, PermissionError, OSError) as exc:
            return ToolResult(ok=False, output=str(exc))
        path = Path(item.abs_path)
        row = self._row_for(path, root_name=item.root_name, title=item.label)
        return ToolResult(
            ok=True,
            output=f"On the desk: {item.label}",
            data=row,
        )

    def _list(self, kwargs: dict[str, Any]) -> ToolResult:
        limit = _cap(kwargs.get("limit"), _DEFAULT_LIMIT, _MAX_LIMIT)
        rows = [
            self._row_for(path, root_name=root_name)
            for root_name, path in self._iter_notes(active_only=True)
        ]
        rows.sort(key=lambda r: (r.get("date") or "", r.get("id") or ""), reverse=True)
        rows = rows[:limit]
        if not rows:
            return ToolResult(
                ok=True,
                output="No notes on the desk.",
                data={"notes": []},
            )
        lines = [f"{row['date'] or '—'}  {row['title']}  {row['path']}" for row in rows]
        lines.append(f"{len(rows)} note(s).")
        return ToolResult(ok=True, output="\n".join(lines), data={"notes": rows})

    def _search(self, kwargs: dict[str, Any]) -> ToolResult:
        query = str(kwargs.get("query") or kwargs.get("text") or "").strip()
        if not query:
            return ToolResult(ok=False, output="search needs query.")
        limit = _cap(kwargs.get("limit"), _SEARCH_DEFAULT, _SEARCH_MAX)
        hits: list[dict[str, Any]] = []
        for root_name, path in self._iter_notes(active_only=False):
            try:
                page = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not _body_matches(page, query):
                continue
            row = self._row_for(path, root_name=root_name, page=page)
            row["excerpt"] = _excerpt(page, query)
            hits.append(row)
            if len(hits) >= limit:
                break
        if not hits:
            return ToolResult(
                ok=True,
                output=f"No notes matching {query!r}.",
                data={"notes": []},
            )
        lines = [f"{row['title']}  {row['path']}\n  {row['excerpt']}" for row in hits]
        lines.append(f"{len(hits)} note(s).")
        return ToolResult(ok=True, output="\n".join(lines), data={"notes": hits})

    def _read(self, kwargs: dict[str, Any]) -> ToolResult:
        raw = str(kwargs.get("id") or kwargs.get("path") or "").strip()
        if not raw:
            return ToolResult(ok=False, output="read needs id or path.")
        try:
            path, root_name = self._resolve_note(raw)
        except PermissionError as exc:
            return ToolResult(ok=False, output=str(exc))
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        try:
            page = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not read that note: {exc}")
        row = self._row_for(path, root_name=root_name, page=page)
        shown = page if len(page) <= _READ_CHARS else page[:_READ_CHARS] + "\n…"
        return ToolResult(ok=True, output=shown, data=row)

    def _iter_notes(self, *, active_only: bool) -> list[tuple[str, Path]]:
        """`.md` files sitting in notes/ under workspace roots. No walk."""
        entries = [self.workspace.active_root()] if active_only else self.workspace.roots
        found: list[tuple[str, Path]] = []
        for entry in entries:
            folder = _notes_folder(entry.path)
            if folder is None:
                continue
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            for child in children:
                note = _contained_note(child, folder)
                if note is not None:
                    found.append((entry.name, note))
        return found

    def _resolve_note(self, raw: str) -> tuple[Path, str]:
        """Map id/path onto a file inside some workspace notes/ folder."""
        candidate = raw.replace("\\", "/").strip()
        if candidate.endswith("/"):
            raise PermissionError("Path outside the notes folder.")
        # A bare stem or filename is looked up inside notes/, never joined
        # onto the project root — otherwise `../secret.md` walks out.
        name = Path(candidate).name
        if candidate in {name, f"{_NOTE_DIR}/{name}"} or "/" not in candidate:
            stem = name[: -len(_NOTE_SUFFIX)] if name.lower().endswith(_NOTE_SUFFIX) else name
            for root_name, path in self._iter_notes(active_only=False):
                if path.stem == stem or path.name == name:
                    return path, root_name
            raise ValueError(f"No note matching {raw!r}.")

        try:
            resolved = self.workspace.resolve_read(candidate)
        except PermissionError:
            raise
        except ValueError as exc:
            raise PermissionError(str(exc)) from exc
        folder = _notes_folder(resolved.root)
        if folder is None:
            raise PermissionError("Path outside the notes folder.")
        note = _contained_note(resolved.path, folder)
        if note is None:
            raise PermissionError("Path outside the notes folder.")
        if not note.is_file():
            raise ValueError(f"No note at {raw!r}.")
        return note, resolved.root_name

    def _row_for(
        self,
        path: Path,
        *,
        root_name: str,
        title: str = "",
        page: str | None = None,
    ) -> dict[str, Any]:
        text = page
        if text is None:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
        heading = (title or "").strip() or _heading(text) or path.stem
        date = _date_of(path, text)
        rel = f"{_NOTE_DIR}/{path.name}"
        return {
            "id": path.stem,
            "title": heading,
            "date": date,
            "path": rel,
            "abs_path": str(path),
            "root_name": root_name,
        }


def _notes_folder(root: Path) -> Path | None:
    try:
        folder = (root / _NOTE_DIR).resolve()
        folder.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    if not folder.is_dir():
        return None
    return folder


def _contained_note(path: Path, folder: Path) -> Path | None:
    """One markdown file whose resolved path is still inside notes/."""
    try:
        if not path.is_file():
            return None
        resolved = path.resolve()
        resolved.relative_to(folder)
    except (OSError, ValueError):
        return None
    if resolved.parent != folder:
        return None
    if resolved.suffix.lower() != _NOTE_SUFFIX:
        return None
    return resolved


def _heading(page: str) -> str:
    for line in (page or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            break
    return ""


def _date_of(path: Path, page: str) -> str:
    hit = _DATE_STEM.match(path.stem)
    if hit:
        return hit.group(1)
    kept = re.search(r"(?im)^Kept\s+(.+?)\.\s*$", page or "")
    if kept:
        return kept.group(1).strip()
    return ""


def _body_matches(page: str, query: str) -> bool:
    hay = (page or "").casefold()
    q = query.strip().casefold()
    if not q or not hay:
        return False
    if q in hay:
        return True
    words = [w for w in q.split() if w]
    return bool(words) and all(w in hay for w in words)


def _excerpt(page: str, query: str) -> str:
    text = " ".join((page or "").split())
    if not text:
        return ""
    hay = text.casefold()
    q = query.strip().casefold()
    idx = hay.find(q)
    if idx < 0:
        for word in q.split():
            idx = hay.find(word)
            if idx >= 0:
                break
        else:
            idx = 0
    start = max(0, idx - 40)
    chunk = text[start : start + _EXCERPT]
    if start > 0:
        chunk = "…" + chunk
    if start + _EXCERPT < len(text):
        chunk = chunk + "…"
    return chunk


def _cap(raw: Any, default: int, ceiling: int) -> int:
    try:
        wanted = int(raw)
    except (TypeError, ValueError):
        return default
    if wanted <= 0:
        return default
    return min(wanted, ceiling)
