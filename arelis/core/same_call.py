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
# Browser snapshot / click stay free — the page can change. open / navigate
# of the same URL is a loop (the solid-state research turn opened QS 5×).
_SKIP_TOOLS = frozenset(
    {
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
    if n == "research_report":
        return _research_report_key(payload)
    if n == "browser":
        return _browser_nav_key(payload)
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
    if name == "research_report":
        return (
            "Already ran research_report on that query this turn; not "
            "researching it again. Answer from the report you have, or "
            "change the question."
        )
    if name == "browser":
        action = str(args.get("action") or "").strip().lower()
        if action == "wait":
            return (
                "Already waited for that URL/text this turn; not waiting "
                "again. The tab is already there. Stop. Tell the user "
                "what they see."
            )
        return (
            "Already opened that URL this turn; not opening it again. "
            "The tab is already there. Stop. Tell the user what they "
            "see (signed in, or login ready). Do not navigate again, "
            "and do not search."
        )
    return (
        f"Already ran {name} with those arguments this turn; not calling it "
        "again. Answer from the prior result, or change the arguments."
    )


def same_call_finish_line(name: str, last_out: str) -> str:
    """User-facing line when a second identical call is blocked.

    The prior successful output is the answer. Shipping a skip sentence
    instead is what made calculator turns say "I already have that result".
    """
    text = (last_out or "").strip()
    if text:
        if len(text) > 800:
            cut = text[:800]
            nl = cut.rfind("\n")
            text = cut[:nl] if nl > 200 else cut
        return text
    if (name or "").strip() == "browser":
        return "I already have that result. The tab is open."
    return "I already have that result this turn."


def is_browser_nav_call(name: str, args: dict[str, Any] | None) -> bool:
    """True for open/navigate — the calls the same-URL fuse owns."""
    if (name or "").strip() != "browser":
        return False
    action = str((args or {}).get("action") or "").strip().lower()
    return action in {"open", "navigate"}


def _browser_nav_key(args: dict[str, Any]) -> str | None:
    """Same open/navigate URL or wait needle is a loop. Snapshot stays free."""
    action = str(args.get("action") or "").strip().lower()
    if action == "wait":
        url = str(args.get("url") or args.get("target") or "").strip().casefold()
        text = " ".join(str(args.get("text") or "").split()).casefold()
        heading = " ".join(str(args.get("heading") or "").split()).casefold()
        if not (url or text or heading):
            return None
        return f"browser|wait|{url}|{text}|{heading}"
    if action not in {"open", "navigate"}:
        return None
    url = str(args.get("url") or "").strip().casefold()
    if not url:
        return None
    url = url.split("#", 1)[0].rstrip("/")
    return f"browser|go|{url}"


def _research_report_key(args: dict[str, Any]) -> str:
    """Same question is a loop even if max_sources / recency change."""
    query = " ".join(str(args.get("query") or "").split()).casefold()
    if not query:
        return _generic_key("research_report", args)
    return f"research_report|{query}"


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
