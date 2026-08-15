"""Fail-tag replan notices after perception or send tools miss.

When scrape / web_search / web_fetch / send_email / send_sms / image fails with a
``[fail:…]`` tag or an explicit ``ok=False``, return one short system nudge.
Does not call tools or skip Allow.
"""

from __future__ import annotations

import re

from arelis.core.evidence import classify_fetch_failure, classify_search_failure

_FAIL_TAG = re.compile(r"\[fail:[a-z0-9_]+\]", re.IGNORECASE)
_REPLAN_TOOLS = frozenset(
    {"scrape", "web_search", "web_fetch", "send_email", "send_sms", "image"}
)
_SEND_TOOLS = frozenset({"send_email", "send_sms"})


def tool_fail_replan_notice(
    name: str,
    output: str,
    *,
    ok: bool | None = None,
) -> str | None:
    """Return a one-shot replan nudge when a tracked tool failed, else None.

    Triggers when ``ok`` is False, or when ``output`` carries a ``[fail:…]``
    tag (scrape / search / send / image), or when web_search clearly found nothing.
    """
    tool = (name or "").strip().lower()
    if tool not in _REPLAN_TOOLS:
        return None

    text = output or ""
    tag_match = _FAIL_TAG.search(text)
    empty_search = tool == "web_search" and _web_search_failed(text)
    failed = ok is False or bool(tag_match) or empty_search
    if not failed:
        return None

    if tag_match:
        tag = tag_match.group(0)
    elif tool == "web_search":
        tag = f"[{classify_search_failure(text)}]"
    elif tool in {"scrape", "web_fetch"}:
        tag = f"[{classify_fetch_failure(text)}]"
    elif tool in _SEND_TOOLS or tool == "image":
        tag = f"[fail:{tool}]"
    else:
        tag = "[fail:other]"

    if tool == "web_search":
        return (
            f"Tool replan: web_search failed ({tag}). "
            "Rephrase the query once, or scrape a known URL directly. "
            "Do not invent results."
        )
    if tool in _SEND_TOOLS:
        kind = "email" if tool == "send_email" else "text"
        return (
            f"Tool replan: {tool} failed ({tag}). "
            f"Tell the user the {kind} was NOT sent. "
            "Do not claim it went out. Fix the error or wait for Allow, then "
            f"call {tool} again only if they still want it sent."
        )
    if tool == "image":
        return (
            f"Tool replan: image failed ({tag}). "
            "Tell the user ComfyUI/image generation failed. "
            "Do NOT call send_sms or send_email. Do not invent a picture path. "
            "Ask them to start ComfyUI by hand if it crashed, then retry image once."
        )
    return (
        f"Tool replan: {tool} failed ({tag}). "
        "Try a different URL once, or use web_fetch for APIs/JSON. "
        "Do not invent page contents."
    )


def _web_search_failed(output: str) -> bool:
    lowered = (output or "").lower()
    return (
        "found nothing" in lowered
        or "web_search failed" in lowered
        or "[fail:" in lowered
    )
