from __future__ import annotations

import asyncio
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

# Directory listings are capped so a node_modules-sized folder cannot flood the
# model's context. The cap is reported in the output, otherwise the model treats
# a clipped listing as the complete contents of the directory.
_MAX_LIST_ENTRIES = 500


class CodeWorkspaceTool:
    name = "workspace"
    description = (
        "Sandboxed file ops under allowed roots. "
        "Actions: list, read, write, edit, keep. "
        "Use list/read freely; write/edit change files. "
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
                "enum": ["list", "read", "write", "edit", "keep"],
                "description": "Workspace action",
            },
            "path": {
                "type": "string",
                "description": "Path relative to a root, or name:relative/path",
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

            if action == "keep":
                body = str(
                    kwargs.get("text")
                    or kwargs.get("content")
                    or kwargs.get("fact")
                    or ""
                )
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
                return await asyncio.to_thread(
                    self._edit, str(path_str), str(old), str(new)
                )

            return ToolResult(ok=False, output=f"Unknown action: {action}")
        except Exception as exc:
            return ToolResult(ok=False, output=f"workspace failed: {exc}")

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
