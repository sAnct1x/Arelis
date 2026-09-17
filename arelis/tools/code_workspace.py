from __future__ import annotations

import asyncio
import fnmatch
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

# Directory listings are capped so a node_modules-sized folder cannot flood the
# model's context. The cap is reported in the output, otherwise the model treats
# a clipped listing as the complete contents of the directory.
_MAX_LIST_ENTRIES = 500

# Folders that make a recursive search useless if walked. `.git` alone holds a
# copy of every string that was ever committed, so grepping it returns the
# history of the answer instead of the answer.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".egg-info",
        ".next",
        ".idea",
        ".vscode",
    }
)

# Caps, in the order they bite. These are not tuning knobs: this runs on a
# worker thread whose event loop also delivers events and drives the confirm
# gate, so an unbounded walk is a frozen stop button.
_SEARCH_MAX_FILES = 4000
_SEARCH_MAX_FILE_BYTES = 2_000_000
_SEARCH_MAX_RESULTS = 200
_SEARCH_DEFAULT_RESULTS = 50
_SEARCH_LINE_CHARS = 200
# Enough to catch a NUL in any real binary header without reading the file.
_BINARY_SNIFF = 8192


def _is_probably_binary(path: Path) -> bool:
    """A NUL byte near the top. Cheap, and wrong only for exotic text encodings.

    Worth having rather than trusting the suffix: `.dat` and no extension at
    all are both common, and dumping a PNG's bytes into the transcript burns
    the context window on noise.
    """
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(_BINARY_SNIFF)
    except OSError:
        return True


def _walk_files(root: Path, *, glob: str = "") -> Iterator[Path]:
    """Every file under root, skipping the folders that only add noise.

    `os.walk` rather than `Path.rglob` specifically so `_SKIP_DIRS` can be
    pruned in place — `rglob` would descend into `node_modules` in full and
    then filter, which is the slow way to get the same list.
    """
    seen = 0
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.endswith(".egg-info")]
        here = Path(current)
        for name in sorted(files):
            if glob and not fnmatch.fnmatch(name, glob):
                continue
            seen += 1
            if seen > _SEARCH_MAX_FILES:
                return
            yield here / name


class CodeWorkspaceTool:
    name = "workspace"
    description = (
        "Sandboxed file ops under allowed roots. "
        "Actions: list, read, grep, find, write, edit, delete, move, rename, "
        "copy, keep. Use list/read/grep/find freely; write/edit change files. "
        "To locate something you do not have the path for, use grep with "
        "query= (searches file contents, returns path:line) or find with "
        "query= (searches file names) — do not walk the tree with repeated "
        "list calls. "
        "Use delete to remove a file they asked you to remove, and "
        "move/rename/copy with to= for the new path — do not read a file and "
        "write it back under another name. "
        "Use keep when the user says keep this / put this on the desk "
        "/ jot this down — that writes a short note into notes/ on the "
        "active project. Do not use memory remember for a page they want "
        "to reopen. With multiple projects, qualify paths as name:relative/path."
    )
    # Registered as read because list/read dominate. write/edit are gated by
    # ToolRegistry.needs_confirm inspecting the action argument.
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "read",
                    "grep",
                    "find",
                    "write",
                    "edit",
                    "delete",
                    "move",
                    "rename",
                    "copy",
                    "keep",
                ],
                "description": "Workspace action",
            },
            "path": {
                "type": "string",
                "description": (
                    "Path relative to a root, or name:relative/path. The "
                    "source for move/rename/copy"
                ),
            },
            "to": {
                "type": "string",
                "description": (
                    "Destination path for move/rename/copy. Must also be "
                    "inside an allowed root; an existing file is never "
                    "overwritten"
                ),
            },
            "text": {
                "type": "string",
                "description": "Note body for action=keep (or use content)",
            },
            "title": {
                "type": "string",
                "description": "Optional short title for action=keep",
            },
            "content": {"type": "string", "description": "Full file content for write"},
            "old": {"type": "string", "description": "Exact text to replace for edit"},
            "new": {"type": "string", "description": "Replacement text for edit"},
            "max_chars": {"type": "integer", "description": "Read truncation limit"},
            "query": {
                "type": "string",
                "description": (
                    "What to search for. Text inside files for grep, part of "
                    "the filename for find. Literal unless regex=true"
                ),
            },
            "glob": {
                "type": "string",
                "description": ("Filename filter for grep/find, e.g. *.py or *.md"),
            },
            "regex": {
                "type": "boolean",
                "description": "Treat query as a regular expression (default false)",
            },
            "max_results": {
                "type": "integer",
                "description": "Cap on grep/find results (default 50, max 200)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, roots: list[str] | WorkspaceRoots) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        # Kept for tests/callers that still inspect .roots as paths.
        self.roots = [r.path for r in self.workspace.roots]

    def _resolve(self, path_str: str, *, for_create: bool = False, for_read: bool = False):
        # Writes never honor external grants; list/read may.
        if for_create:
            return self.workspace.resolve(path_str, for_create=True)
        if for_read:
            return self.workspace.resolve_read(path_str)
        return self.workspace.resolve(path_str, for_create=False)

    async def run(self, **kwargs: Any) -> ToolResult:
        action = (kwargs.get("action") or "").lower()
        path_str = kwargs.get("path")
        if not action:
            return ToolResult(ok=False, output="Missing action")
        try:
            if action == "list":
                # Omitted path + multiple roots → project names (discovery).
                # Explicit "." lists the active project's root.
                if (path_str is None or str(path_str).strip() == "") and len(self.workspace) > 1:
                    return ToolResult(
                        ok=True,
                        output="\n".join(
                            f"[project] {name}"
                            + (" (active)" if name == self.workspace.active else "")
                            for name in self.workspace.names()
                        ),
                    )
                return await asyncio.to_thread(self._list, path_str or ".")

            if action in {"grep", "search"}:
                return await asyncio.to_thread(
                    self._grep,
                    str(path_str or "."),
                    str(kwargs.get("query") or kwargs.get("text") or ""),
                    glob=str(kwargs.get("glob") or ""),
                    regex=bool(kwargs.get("regex")),
                    max_results=kwargs.get("max_results"),
                )
            if action == "find":
                return await asyncio.to_thread(
                    self._find,
                    str(path_str or "."),
                    str(kwargs.get("query") or kwargs.get("name") or ""),
                    glob=str(kwargs.get("glob") or ""),
                    max_results=kwargs.get("max_results"),
                )

            if action == "keep":
                body = str(kwargs.get("text") or kwargs.get("content") or kwargs.get("fact") or "")
                title = str(kwargs.get("title") or "")
                return await asyncio.to_thread(self._keep, body, title)

            if not path_str:
                return ToolResult(ok=False, output="Missing path")

            # Every branch below touches the disk. Filesystem calls block, and
            # this coroutine shares its event loop with event delivery and the
            # confirm gate, so a large file would otherwise freeze the UI and
            # make the stop button unresponsive.
            if action == "read":
                return await asyncio.to_thread(
                    self._read, str(path_str), int(kwargs.get("max_chars", 100000))
                )
            if action == "write":
                content = kwargs.get("content")
                if content is None:
                    return ToolResult(ok=False, output="Missing content")
                return await asyncio.to_thread(self._write, str(path_str), str(content))
            if action == "edit":
                old = kwargs.get("old")
                new = kwargs.get("new")
                if old is None or new is None:
                    return ToolResult(ok=False, output="edit requires old and new")
                return await asyncio.to_thread(self._edit, str(path_str), str(old), str(new))

            if action in {"delete", "remove"}:
                return await asyncio.to_thread(self._delete, str(path_str))
            if action in {"move", "rename", "copy"}:
                to = kwargs.get("to") or kwargs.get("dest") or kwargs.get("new_path")
                if not to:
                    return ToolResult(
                        ok=False,
                        output=f"{action} requires to (the new path).",
                    )
                return await asyncio.to_thread(
                    self._relocate, str(path_str), str(to), copy=action == "copy"
                )

            return ToolResult(ok=False, output=f"Unknown action: {action}")
        except PermissionError as exc:
            return ToolResult(
                ok=False,
                output=(
                    f"{exc} Add that folder in Settings → roots, or Allow a "
                    "read of the path they named. Do not list a parent folder "
                    "(C:\\Users, Documents, …)."
                ),
            )
        except Exception as exc:
            return ToolResult(ok=False, output=f"workspace failed: {exc}")

    def _cap(self, raw: Any) -> int:
        try:
            wanted = int(raw)
        except (TypeError, ValueError):
            wanted = _SEARCH_DEFAULT_RESULTS
        if wanted <= 0:
            wanted = _SEARCH_DEFAULT_RESULTS
        return min(wanted, _SEARCH_MAX_RESULTS)

    def _search_root(self, path_str: str) -> tuple[Path, str]:
        """(folder to walk, label). Raises PermissionError outside the roots.

        `resolve_read` is what keeps a search inside the sandbox — without it
        `path="../.."` walks the drive, which would make this the widest hole
        in the tool rather than its most useful action.
        """
        resolved = self._resolve(path_str or ".", for_read=True)
        target = resolved.path
        if target.is_file():
            target = target.parent
        return target, resolved.qualified(multi=len(self.workspace) > 1)

    def _grep(
        self,
        path_str: str,
        query: str,
        *,
        glob: str = "",
        regex: bool = False,
        max_results: Any = None,
    ) -> ToolResult:
        """Search file contents. Roadmap 4.2.

        Without this, "where is X defined" had no route at all: the model had to
        walk the tree with repeated `list` calls, and `same_call` blocks that —
        correctly, since from the outside it looks like a stuck loop. The guard
        was fighting a missing capability.
        """
        needle = (query or "").strip()
        if not needle:
            return ToolResult(
                ok=False,
                output="grep needs a query (the text to search for).",
            )
        if regex:
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error as exc:
                return ToolResult(
                    ok=False,
                    output=f"Bad regex: {exc}. Drop regex=true to search for it literally.",
                )
        else:
            # Literal by default. Most searches are for a name that contains
            # (, ., * or + — treating those as regex silently changes the
            # question, or raises on text the user typed verbatim.
            pattern = re.compile(re.escape(needle), re.IGNORECASE)

        root, label = self._search_root(path_str)
        if not root.is_dir():
            return ToolResult(ok=False, output=f"Not found: {label}")
        cap = self._cap(max_results)
        hits: list[str] = []
        files_with_hits = 0
        truncated = False
        for file in _walk_files(root, glob=glob):
            if len(hits) >= cap:
                truncated = True
                break
            try:
                if file.stat().st_size > _SEARCH_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if _is_probably_binary(file):
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = self._display_rel(file)
            found_here = False
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                found_here = True
                body = line.strip()[:_SEARCH_LINE_CHARS]
                hits.append(f"{rel}:{lineno}: {body}")
                if len(hits) >= cap:
                    truncated = True
                    break
            if found_here:
                files_with_hits += 1
        if not hits:
            where = f" under {label}" if path_str not in {"", "."} else ""
            scope = f" matching {glob}" if glob else ""
            return ToolResult(
                ok=True,
                output=f"No match for {needle!r}{where}{scope}.",
                data={"action": "grep", "matches": 0},
            )
        lines = list(hits)
        if truncated:
            lines.append(
                f"[stopped at {cap} matches — narrow it with glob= or path=, or raise max_results]"
            )
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={
                "action": "grep",
                "matches": len(hits),
                "files": files_with_hits,
                "truncated": truncated,
            },
        )

    def _find(
        self,
        path_str: str,
        query: str,
        *,
        glob: str = "",
        max_results: Any = None,
    ) -> ToolResult:
        """Search file *names*. "Where is drive.py" is a different question to grep."""
        needle = (query or "").strip().lower()
        if not needle and not glob:
            return ToolResult(
                ok=False,
                output="find needs a query (part of the name) or a glob.",
            )
        root, label = self._search_root(path_str)
        if not root.is_dir():
            return ToolResult(ok=False, output=f"Not found: {label}")
        cap = self._cap(max_results)
        found: list[str] = []
        truncated = False
        for file in _walk_files(root, glob=glob):
            if needle and needle not in file.name.lower():
                continue
            if len(found) >= cap:
                truncated = True
                break
            found.append(self._display_rel(file))
        if not found:
            asked = needle or glob
            return ToolResult(
                ok=True,
                output=f"No file matching {asked!r} under {label}.",
                data={"action": "find", "matches": 0},
            )
        lines = list(found)
        if truncated:
            lines.append(f"[stopped at {cap} names — narrow it with glob= or path=]")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"action": "find", "matches": len(found), "truncated": truncated},
        )

    def _display_rel(self, file: Path) -> str:
        """Path as the user would type it back, so a hit can go straight into read."""
        for entry in self.workspace.roots:
            try:
                rel = file.resolve().relative_to(entry.path.resolve())
            except (ValueError, OSError):
                continue
            shown = rel.as_posix()
            return f"{entry.name}:{shown}" if len(self.workspace) > 1 else shown
        return file.name

    def _list(self, path_str: str) -> ToolResult:
        resolved = self._resolve(path_str, for_read=True)
        target = resolved.path
        if not target.exists():
            label = resolved.qualified(multi=len(self.workspace) > 1)
            return ToolResult(ok=False, output=f"Not found: {label}")
        if target.is_file():
            return ToolResult(
                ok=True,
                output=resolved.qualified(multi=len(self.workspace) > 1),
                data=self._path_data(resolved),
            )
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        shown = entries[:_MAX_LIST_ENTRIES]
        lines = [("[dir] " if p.is_dir() else "[file] ") + p.name for p in shown]
        if len(entries) > len(shown):
            lines.append(f"[{len(entries) - len(shown)} more entries not shown]")
        return ToolResult(
            ok=True,
            output="\n".join(lines) or "(empty)",
            data=self._path_data(resolved),
        )

    def _read(self, path_str: str, max_chars: int) -> ToolResult:
        resolved = self._resolve(path_str, for_read=True)
        path = resolved.path
        if not path.is_file():
            return ToolResult(ok=False, output=f"Not a file: {path}")
        text = redact_secrets(path.read_text(encoding="utf-8", errors="replace"))
        out = text[:max_chars]
        if len(text) > max_chars:
            out += f"\n\n[truncated to {max_chars} chars]"
        return ToolResult(ok=True, output=out, data=self._path_data(resolved))

    def _write(self, path_str: str, content: str) -> ToolResult:
        resolved = self._resolve(path_str, for_create=True)
        path = resolved.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"Wrote {resolved.qualified(multi=len(self.workspace) > 1)}",
            data=self._path_data(resolved),
        )

    def _edit(self, path_str: str, old: str, new: str) -> ToolResult:
        # Edit is a write — sandbox only (no external grants); honor read_only.
        resolved = self.workspace.resolve(path_str, for_write=True)
        path = resolved.path
        if not path.is_file():
            return ToolResult(ok=False, output=f"Not a file: {path}")
        text = path.read_text(encoding="utf-8")
        occurrences = text.count(old)
        if occurrences == 0:
            return ToolResult(ok=False, output="old string not found in file")
        # Replace once only. If the anchor is ambiguous the model gets told so
        # and can widen it, which is safer than silently editing the first of
        # several matches and reporting success.
        if occurrences > 1:
            return ToolResult(
                ok=False,
                output=(
                    f"old string appears {occurrences} times in {path}; "
                    "include more surrounding context so the edit is unambiguous"
                ),
            )
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"Edited {resolved.qualified(multi=len(self.workspace) > 1)}",
            data=self._path_data(resolved),
        )

    def _delete(self, path_str: str) -> ToolResult:
        """Remove one file, or one already-empty directory.

        for_write, not for_read: containment and read-only both apply, and an
        external read grant must not become licence to delete the file it
        opened. There is deliberately no recursive form — emptying a tree is
        the single mistake with no undo, so the model is not given a verb for
        it.
        """
        resolved = self.workspace.resolve(path_str, for_write=True)
        path = resolved.path
        label = resolved.qualified(multi=len(self.workspace) > 1)
        if not path.exists():
            return ToolResult(ok=False, output=f"Not found: {label}")
        if path.is_dir():
            if any(path.iterdir()):
                return ToolResult(
                    ok=False,
                    output=(
                        f"{label} is a directory and is not empty. Delete the "
                        "files inside it first — there is no recursive delete."
                    ),
                )
            path.rmdir()
            return ToolResult(
                ok=True,
                output=f"Deleted empty directory {label}",
                data=self._path_data(resolved),
            )
        path.unlink()
        return ToolResult(ok=True, output=f"Deleted {label}", data=self._path_data(resolved))

    def _relocate(self, path_str: str, to_str: str, *, copy: bool) -> ToolResult:
        """move / rename / copy. Both ends are contained; nothing is clobbered."""
        import shutil

        src = self.workspace.resolve(path_str, for_write=True)
        # for_create so the destination need not exist yet, but it still has to
        # land inside a writable root — containment on the source alone would
        # let a move carry a file out of the sandbox.
        dst = self.workspace.resolve(to_str, for_create=True)
        multi = len(self.workspace) > 1
        src_label = src.qualified(multi=multi)
        dst_label = dst.qualified(multi=multi)
        verb = "copy" if copy else "move"

        if not src.path.exists():
            return ToolResult(ok=False, output=f"Not found: {src_label}")
        if dst.path.exists():
            return ToolResult(
                ok=False,
                output=(
                    f"{dst_label} already exists. Pick another name, or delete "
                    f"it first — {verb} will not overwrite it."
                ),
            )
        if copy and src.path.is_dir():
            return ToolResult(
                ok=False,
                output=f"{src_label} is a directory; copy handles files only.",
            )

        dst.path.parent.mkdir(parents=True, exist_ok=True)
        if copy:
            shutil.copy2(src.path, dst.path)
            word = "Copied"
        else:
            shutil.move(str(src.path), str(dst.path))
            word = "Moved"
        return ToolResult(
            ok=True,
            output=f"{word} {src_label} → {dst_label}",
            data={**self._path_data(dst), "from": src_label},
        )

    def _keep(self, text: str, title: str) -> ToolResult:
        from arelis.desk import write_note

        item = write_note(self.workspace, text, title=title)
        resolved = self.workspace.resolve(item.abs_path)
        return ToolResult(
            ok=True,
            output=f"On the desk: {item.label}",
            data={
                **self._path_data(resolved),
                "kind": "note",
                "title": item.label,
            },
        )

    def _path_data(self, resolved) -> dict[str, str]:
        multi = len(self.workspace) > 1
        label = (
            str(resolved.path)
            if resolved.root_name == "external"
            else resolved.qualified(multi=multi)
        )
        return {
            "path": label,
            "abs_path": str(resolved.path),
            "root_name": resolved.root_name,
        }
