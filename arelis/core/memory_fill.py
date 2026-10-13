"""Put this turn's computed number on a remembered label that has none."""

from __future__ import annotations

import re
from typing import Any

_DIGIT = re.compile(r"\d")
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_RESULT = re.compile(rf"^(?P<left>.+?) = (?P<num>{_NUMBER})(?:\s+(?P<unit>[A-Za-z][A-Za-z0-9_]*))?")
_NUMBER_TOKEN = re.compile(_NUMBER)
_COMPUTED_TOOLS = frozenset({"calculator", "units"})


def fill_memory_remember_args(
    args: dict[str, Any],
    *,
    messages: list[dict[str, Any]] | None,
    user_text: str,
) -> dict[str, Any]:
    """Append the last ok calculator or units value when the fact has no digit.

    Only tool results after this turn's ask count. A fact that already
    contains a digit is left as the model wrote it.
    """
    if str(args.get("action") or "").strip().lower() != "remember":
        return args
    fact = str(args.get("fact") or "").strip()
    if not fact or _DIGIT.search(fact):
        return args
    computed = _computed_this_turn(messages, user_text)
    if not computed:
        return args
    last = computed[-1]
    unit = _unit_for(last, computed)
    filled = f"{fact}: {last[2]}"
    if unit:
        filled = f"{filled} {unit}"
    updated = dict(args)
    updated["fact"] = filled
    return updated


def _computed_this_turn(
    messages: list[dict[str, Any]] | None,
    user_text: str,
) -> list[tuple[str, str, str, str]]:
    """(tool, expression, number, unit) for ok results after the current ask."""
    found: list[tuple[str, str, str, str]] = []
    for message in _messages_after_ask(messages, user_text):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "tool":
            continue
        tool = str(message.get("tool_name") or "").strip()
        if tool not in _COMPUTED_TOOLS:
            continue
        parsed = _parse_result(str(message.get("content") or ""))
        if parsed is None:
            continue
        expression, number, unit = parsed
        found.append((tool, expression, number, unit))
    return found


def _messages_after_ask(
    messages: list[dict[str, Any]] | None,
    user_text: str,
) -> list[dict[str, Any]]:
    """Rows after this turn's ask. Earlier turns stay out."""
    rows = list(messages or [])
    needle = (user_text or "").strip()
    if not needle:
        return []
    start = None
    for index, message in enumerate(rows):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip() == needle:
            start = index + 1
    if start is None:
        return []
    return rows[start:]


def _parse_result(content: str) -> tuple[str, str, str] | None:
    line = (content or "").strip().splitlines()[0].strip() if content else ""
    hit = _RESULT.match(line)
    if hit is None:
        return None
    unit = hit.group("unit") or ""
    return hit.group("left").strip(), hit.group("num"), unit


def _unit_for(
    last: tuple[str, str, str, str],
    computed: list[tuple[str, str, str, str]],
) -> str:
    """Unit from the conversion when that number was reused, else none."""
    tool, expression, number, unit = last
    if tool == "units":
        return _spoken_unit(unit, number)
    for earlier_tool, _expr, earlier_number, earlier_unit in reversed(computed):
        if earlier_tool != "units":
            continue
        if _expression_uses(expression, earlier_number):
            return _spoken_unit(earlier_unit, earlier_number)
    return ""


def _expression_uses(expression: str, number: str) -> bool:
    for token in _NUMBER_TOKEN.findall(expression or ""):
        if _same_number(token, number):
            return True
    return False


def _same_number(left: str, right: str) -> bool:
    try:
        a = float(left)
        b = float(right)
    except ValueError:
        return False
    scale = max(1.0, abs(a), abs(b))
    return abs(a - b) <= 1e-9 * scale


def _spoken_unit(unit: str, number: str) -> str:
    word = (unit or "").strip()
    if not word:
        return ""
    try:
        value = abs(float(number))
    except ValueError:
        value = None
    if value is not None and abs(value - 1.0) <= 1e-9:
        return word
    if word.endswith("s"):
        return word
    return f"{word}s"
