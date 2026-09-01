"""Same successful tool+args this turn is a loop, not more work.

The round cap is a fuse. This is the actual stop: a second list of the
same folder, a second read of the same file, a second rooms get. A
different path or different args still run. Failed calls do not count,
so a retry after an error is allowed. Browser snapshots are not gated —
the page can change after a click.
"""

from __future__ import annotations

import json
from typing import Any

# World changes mid-turn, or another gate already owns the repeat.
_SKIP_TOOLS = frozenset(
    {
        "browser",
        "camera",
        "vision",
        "image",
        "image_edit",
        "weather",
        "scrape",
        "web_fetch",
        "web_search",
        "send_sms",
        "send_email",
        "inbox",
        "run_script",
        "schedule",
    }
)

_WORKSPACE_WRITES = frozenset({"write", "edit", "keep"})


def normalize_workspace_path(path: str, action: str) -> str:
    """`.` / empty / trailing slash are one list of the project root."""
    raw = (path or "").strip().replace("\\", "/")
    while raw.endswith("/") and raw != "/":
        raw = raw[:-1]
    act = (action or "").strip().lower()
    if act == "list" and raw in {"", ".", "./"}:
        return "."
    return raw


def same_call_key(name: str, args: dict[str, Any] | None) -> str | None:
    """Stable key, or None when a repeat is allowed (or another gate owns it)."""
    n = (name or "").strip()
    if not n or n in _SKIP_TOOLS:
        return None
    payload = args or {}
    if n == "workspace":
        return _workspace_key(payload)
    return _generic_key(n, payload)


def already_ran_same_call(
    same_ok: set[str], name: str, args: dict[str, Any] | None
) -> str | None:
    """Notice to inject when this exact call already succeeded, else None."""
    key = same_call_key(name, args)
    if key is None or key not in same_ok:
        return None
    return same_call_notice(name, args or {})


def record_same_call(
    same_ok: set[str], name: str, args: dict[str, Any] | None
) -> None:
    """Remember a successful call. A write drops reads of that path."""
    payload = args or {}
    key = same_call_key(name, payload)
    if key:
        same_ok.add(key)
    if name == "workspace" and str(payload.get("action") or "").strip().lower() in {
        "write",
        "edit",
    }:
        _invalidate_workspace_reads(same_ok, str(payload.get("path") or ""))


def same_call_notice(name: str, args: dict[str, Any]) -> str:
    if name == "workspace":
        action = str(args.get("action") or "").strip().lower() or "that action"
        path = normalize_workspace_path(str(args.get("path") or ""), action)
        if action == "list":
            return (
                f"Already listed {path} this turn; not listing it again. "
                "Read a file you have not opened, or answer from what you have."
            )
        if action == "read":
            shown = path or "that file"
            return (
                f"Already read {shown} this turn; not reading it again. "
                "Open a different file, or answer from that text."
            )
    return (
        f"Already ran {name} with those arguments this turn; not calling it "
        "again. Answer from the prior result, or change the arguments."
    )


def _workspace_key(args: dict[str, Any]) -> str | None:
    action = str(args.get("action") or "").strip().lower()
    if not action:
        return None
    if action in _WORKSPACE_WRITES:
        return _generic_key("workspace", args)
    path = normalize_workspace_path(str(args.get("path") or ""), action)
    if action == "list":
        return f"workspace|list|{path}"
    if action == "read":
        return f"workspace|read|{path}|{args.get('max_chars', '')}"
    return _generic_key("workspace", args)


def _generic_key(name: str, args: dict[str, Any]) -> str:
    try:
        payload = json.dumps(args, sort_keys=True, default=str)
    except TypeError:
        payload = repr(args)
    return f"{name}|{payload}"


def _invalidate_workspace_reads(same_ok: set[str], path: str) -> None:
    """A write/edit means a later read of that file is new work."""
    norm = normalize_workspace_path(path, "read")
    if not norm:
        return
    parent = norm.rsplit("/", 1)[0] if "/" in norm else "."
    drop = {
        key
        for key in same_ok
        if key.startswith(f"workspace|read|{norm}|")
        or key == f"workspace|list|{norm}"
        or key == f"workspace|list|{parent}"
    }
    same_ok -= drop
