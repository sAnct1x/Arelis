"""What an Allow card shows before a workspace write or a process start.

The card is the seatbelt. A 9B will bury a delete in a file and then ask to
run it. The working directory being the project does not stop that process
from touching the rest of the disk, so the card says so, and it quotes the
lines that look like a delete.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

_DIFF_CHARS = 200_000
_DIFF_LINES = 80
_HEAD_LINES = 40
_SCAN_BYTES = 512_000

_LOUD = re.compile(
    r"(?i)("
    r"shutil\.rmtree|"
    r"os\.remove\b|"
    r"os\.unlink\b|"
    r"os\.rmdir\b|"
    r"\.unlink\(|"
    r"Remove-Item|"
    r"\brmdir\b|"
    r"\bdel\s+/|"
    r"\brm\s+-"
    r"|diskpart|"
    r"\bformat\s+[a-zA-Z]:|"
    r"git\s+clean\b|"
    r"git\s+reset\s+--hard"
    r")"
)


def loud_lines(text: str, *, limit: int = 12) -> list[str]:
    """Lines that look like a delete. Empty when the text is quiet."""
    found: list[str] = []
    for lineno, line in enumerate((text or "").splitlines(), start=1):
        if not _LOUD.search(line):
            continue
        body = line.strip()
        if len(body) > 200:
            body = body[:199] + "…"
        found.append(f"{lineno}: {body}")
        if len(found) >= limit:
            break
    return found


def unified_preview(before: str, after: str, label: str) -> str:
    """A short unified diff. Both sides are capped so a huge write cannot stall the card."""
    old = _clip(before)
    new = _clip(after)
    diff = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            lineterm="",
        )
    )
    if not diff:
        return "(no change)"
    extra = ""
    if len(diff) > _DIFF_LINES:
        extra = f"\n…({len(diff) - _DIFF_LINES} more lines)"
        diff = diff[:_DIFF_LINES]
    return redact_secrets("\n".join(diff) + extra)


def workspace_confirm(roots: WorkspaceRoots, args: dict[str, Any]) -> str:
    """Card body for a workspace call. Reads the file. Does not write it."""
    action = str(args.get("action") or "").strip().lower() or "?"
    path = str(args.get("path") or "").strip() or "(path)"
    lines = [f"Workspace {action}", f"Path: {path}"]
    if action == "delete" or action == "remove":
        lines.append("Removes this file. There is no trash.")
        return "\n".join(lines)
    if action in {"move", "rename", "copy"}:
        dest = str(args.get("to") or args.get("dest") or "").strip() or "(missing)"
        lines.append(f"To: {dest}")
        lines.append("Will not overwrite a file that is already there.")
        return "\n".join(lines)
    if action == "keep":
        body = str(args.get("text") or args.get("content") or "")
        lines.append("Writes a note under notes/ on the active project.")
        lines.append("")
        lines.append(redact_secrets(body)[:1200] or "(empty)")
        return "\n".join(lines)
    if action in {"patch", "apply"}:
        blob = args.get("diff")
        if blob is None:
            blob = args.get("patch")
        if blob is None:
            blob = args.get("content")
        text = str(blob or "")
        lines.append("Applies this diff exactly. All files, or none.")
        _append_loud(lines, "\n".join(_added_only(text)))
        lines.append("")
        shown = redact_secrets(text)
        if len(shown) > 4000:
            shown = shown[:3999] + "…"
        lines.append(shown or "(empty diff)")
        return "\n".join(lines)
    if action == "edit":
        return _edit_confirm(roots, args, lines, path)
    if action == "write":
        return _write_confirm(roots, args, lines, path)
    return "\n".join(lines)


def run_script_confirm(roots: WorkspaceRoots, args: dict[str, Any]) -> str:
    """Card body for run_script. The process runs as the user."""
    path = str(args.get("path") or "").strip() or "(path)"
    extra = _as_argv(args.get("args"))
    lines = [
        "Run this program",
        "This process runs as you. It can touch the rest of the disk.",
        f"Path: {path}",
    ]
    try:
        hit = roots.resolve(path, for_write=False)
    except Exception as exc:
        lines.append(str(exc))
        return "\n".join(lines)
    lines.append(f"Working directory: {hit.root}")
    argv = [hit.path.name, *extra]
    lines.append("Argv: " + json.dumps(argv, ensure_ascii=False))
    file_text = _read_capped(hit.path)
    _append_loud(lines, file_text)
    head = "\n".join(file_text.splitlines()[:_HEAD_LINES])
    lines.append("")
    lines.append(redact_secrets(head) if head else "(empty file)")
    if len(file_text.splitlines()) > _HEAD_LINES:
        lines.append(f"…({len(file_text.splitlines()) - _HEAD_LINES} more lines)")
    return "\n".join(lines)


def run_task_confirm(
    *,
    name: str,
    cwd: str,
    argv: list[str],
    detail: str,
) -> str:
    """Card body for a named project task. `detail` is the script body or the argv source."""
    lines = [
        f"Run {name}",
        "This process runs as you. It can touch the rest of the disk.",
        f"Working directory: {cwd}",
        "Argv: " + json.dumps(argv, ensure_ascii=False),
    ]
    blob = detail or ""
    if blob.strip():
        lines.append("")
        lines.append(redact_secrets(blob.strip())[:2000])
    _append_loud(lines, blob + "\n" + "\n".join(argv))
    return "\n".join(lines)


def _edit_confirm(
    roots: WorkspaceRoots, args: dict[str, Any], lines: list[str], path: str
) -> str:
    old = str(args.get("old") if args.get("old") is not None else "")
    new = str(args.get("new") if args.get("new") is not None else args.get("new_text") or "")
    try:
        hit = roots.resolve(path, for_write=True)
    except Exception as exc:
        lines.append(str(exc))
        return "\n".join(lines)
    if not hit.path.is_file():
        lines.append("Not a file yet. This edit will not apply.")
        return "\n".join(lines)
    before = _read_capped(hit.path)
    count = before.count(old) if old else 0
    if not old or count != 1:
        lines.append(
            "This edit will not apply. "
            + ("old string is empty." if not old else f"old string appears {count} times.")
        )
        lines.append("")
        lines.append(unified_preview(old, new, path))
        return "\n".join(lines)
    after = before.replace(old, new, 1)
    _append_loud(lines, after)
    lines.append("")
    lines.append(unified_preview(before, after, path))
    return "\n".join(lines)


def _write_confirm(
    roots: WorkspaceRoots, args: dict[str, Any], lines: list[str], path: str
) -> str:
    content = str(args.get("content") if args.get("content") is not None else "")
    try:
        hit = roots.resolve(path, for_create=True)
    except Exception as exc:
        lines.append(str(exc))
        return "\n".join(lines)
    before = _read_capped(hit.path) if hit.path.is_file() else ""
    if hit.path.is_file():
        lines.append("Replaces the file on disk.")
    else:
        lines.append("New file.")
    _append_loud(lines, content)
    lines.append("")
    lines.append(unified_preview(before, content, path))
    return "\n".join(lines)


def _append_loud(lines: list[str], text: str) -> None:
    found = loud_lines(text)
    if not found:
        return
    lines.append("")
    lines.append("Delete-looking lines:")
    lines.extend(found)


def _added_only(diff_text: str) -> list[str]:
    out: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
    return out


def _clip(text: str) -> str:
    if len(text) <= _DIFF_CHARS:
        return text
    return text[:_DIFF_CHARS] + "\n…(truncated for the card)"


def _read_capped(path: Path) -> str:
    try:
        raw = path.read_bytes()[:_SCAN_BYTES]
    except OSError:
        return ""
    if b"\x00" in raw[:8192]:
        return "(binary file)"
    return raw.decode("utf-8", errors="replace")


def _as_argv(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return [str(raw)]
