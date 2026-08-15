"""When a model round emits several independent reads, run them together.

Writes, side effects, and Allow-gated calls stay serial. Wrong-tool redirects
(web_search on a weather/SMS turn) also stay serial so the existing gates fire.
"""

from __future__ import annotations

from typing import Any

from arelis.tools.base import ToolRegistry, capability_class

_REDIRECT_EXPECTED = frozenset({"weather", "send_sms", "send_email", "agenda"})
_DUP_GATED = frozenset({"weather", "image", "vision", "send_sms", "send_email"})


def should_fanout_reads(
    calls: list[tuple[str, dict[str, Any]]],
    *,
    tool_names: set[str],
    expected_tools: set[str],
    tools: ToolRegistry,
    confirm_writes: bool = True,
    confirm_image: bool = True,
    confirm_send: bool = True,
    confirm_browser: bool = True,
    confirm_vision: bool = True,
    allow_writes_this_turn: bool = False,
    tools_used: set[str] | None = None,
    web_search_ok: set[str] | None = None,
) -> bool:
    """True when every call in this round is a confirm-free READ."""
    if len(calls) < 2:
        return False
    names = [str(name or "") for name, _args in calls]
    if any(names.count(n) > 1 and n in _DUP_GATED for n in names):
        return False
    used = tools_used or set()
    search_ok = web_search_ok or set()
    redirect_risk = bool(expected_tools & _REDIRECT_EXPECTED)
    for name, args in calls:
        if name not in tool_names:
            return False
        if name == "weather" and "weather" in used:
            return False
        if name == "image" and "image" in used:
            return False
        if name == "web_search":
            query = str(args.get("query") or "").strip().casefold()
            if query and query in search_ok:
                return False
        if capability_class(name, args) != "READ":
            return False
        if tools.needs_confirm(
            name,
            args,
            confirm_writes=confirm_writes
            and (not allow_writes_this_turn or name == "agenda"),
            confirm_image=confirm_image and not allow_writes_this_turn,
            confirm_send=confirm_send,
            confirm_browser=confirm_browser and not allow_writes_this_turn,
            confirm_vision=confirm_vision and not allow_writes_this_turn,
        ):
            return False
        if name == "web_search" and redirect_risk:
            return False
    return True
