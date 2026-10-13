"""Bench cities must not show up in a tool schema or the system prompt.

Matrix items S16, C02, and C22 ask for Springfield, Illinois. The weather
place parameter used that same city as its example, so the schema hinted
at the answer. This test loads city and place names from the bench items
and the eval boards, then fails if that text is in a tool schema or in
the system prompt.

The example is now Lyon, France. That city string is 9 characters shorter
(21 to 12). schema_token_estimate counts the old city as 6 Qwen tokens
and the new one as 4. Parameter descriptions are stripped before the
tools array is built, so the worst-profile golden stays 24,429 characters
and 7,392 Qwen tokens, and the prompt golden does not move.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any

import arelis.tools as tools_pkg
from arelis.core.agent_loop import static_prefix_text
from arelis.core.compact_prompt import COMPACT_TOOL_POLICY, format_tool_catalog
from arelis.core.native_tool_calling import NATIVE_PARAM_HINTS
from arelis.mobile import PHONE_PERSONA_TAIL
from arelis.rooms import PHYSICS_ALIASES, PHYSICS_DISPLAY_NAME

_ROOT = Path(__file__).resolve().parents[1]
_PAIR = re.compile(
    r"\b([A-Z][a-z]+(?:[ \-][A-Z][a-z]+)*)"
    r"\s*,\s*"
    r"([A-Z][a-z]+(?:[ \-][A-Z][a-z]+)*)\b"
)
_DEST = re.compile(
    r"\b(?:go to|weather in|forecast for|directions to|outside here in|table at)"
    r"\s+(?:the\s+)?"
    r"([A-Z][a-z]+(?:[ \-][A-Z][a-z]+)*)"
)


def _not_a_city() -> frozenset[str]:
    """Room labels the travel grammar also matches. They are not bench cities."""
    names = {PHYSICS_DISPLAY_NAME}
    names |= {alias.replace("-", " ").title() for alias in PHYSICS_ALIASES}
    return frozenset(names)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.extend(_strings(key))
            out.extend(_strings(item))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_strings(item))
        return out
    return []


def _matrix_items() -> list[Any]:
    scripts = str(_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import live_matrix_items

    return [*live_matrix_items.ITEMS, *live_matrix_items.COMMS_ITEMS]


def bench_texts() -> list[str]:
    """User text, notes, and scripted answers from the bench and the eval boards."""
    from arelis.eval.live_board import live_board_turns
    from arelis.eval.live_fifty import live_fifty_turns
    from arelis.eval.scenarios import SCENARIOS
    from arelis.eval.skill_retrieval import RETRIEVAL_CASES
    from arelis.eval.soak_scenarios import limb_catalog_turns, production_bounce_turns
    from arelis.eval.tool_choice import CHOICE_CASES

    texts: list[str] = []
    for item in _matrix_items():
        texts.extend(_strings(item.prompts))
        texts.extend(_strings(item.notes))
        texts.extend(_strings(item.ans_all))
        texts.extend(_strings(item.ans_any))
        texts.extend(_strings(item.ans_none))
    for scenario in SCENARIOS:
        texts.extend(
            _strings(
                (
                    scenario.user,
                    scenario.notes,
                    scenario.script,
                    scenario.expect_args,
                    scenario.expect_answer_contains,
                    scenario.expect_tool_result_contains,
                )
            )
        )
    turns = [
        *live_fifty_turns(),
        *live_board_turns(),
        *production_bounce_turns(),
        *limb_catalog_turns(),
    ]
    for turn in turns:
        texts.extend(
            _strings(
                (
                    turn.user,
                    turn.notes,
                    turn.script,
                    turn.expect_args,
                    turn.expect_answer_contains,
                    turn.expect_answer_any,
                )
            )
        )
    for case in CHOICE_CASES:
        texts.extend(_strings((case.utterance, case.note)))
    for case in RETRIEVAL_CASES:
        texts.extend(_strings((case.user, case.notes)))
    return texts


def bench_place_names() -> frozenset[str]:
    """Cities and places named in the bench and eval text.

    "City, Region" pairs contribute both words. Travel and weather lines
    contribute the destination. Room names such as Reality are dropped.
    """
    skip = _not_a_city()
    found: set[str] = set()
    for text in bench_texts():
        for match in _PAIR.finditer(text):
            found.add(match.group(1))
            found.add(match.group(2))
        for match in _DEST.finditer(text):
            found.add(match.group(1))
    return frozenset(name for name in found if name not in skip)


def _tool_schema_texts() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _, obj in inspect.getmembers(tools_pkg, inspect.isclass):
        name = getattr(obj, "name", None)
        schema = getattr(obj, "parameters_schema", None)
        if not isinstance(name, str) or not isinstance(schema, dict) or name in seen:
            continue
        seen.add(name)
        description = str(getattr(obj, "description", "") or "")
        rows.append((f"tool:{name}", description + "\n" + json.dumps(schema)))
    rows.append(("short:catalog", format_tool_catalog()))
    for (tool_name, param_name), description in NATIVE_PARAM_HINTS.items():
        rows.append((f"hint:{tool_name}.{param_name}", description))
    return rows


def _system_prompt_texts() -> list[tuple[str, str]]:
    persona = (_ROOT / "arelis" / "persona" / "arelis.md").read_text(encoding="utf-8")
    return [
        ("system:compact_policy", COMPACT_TOOL_POLICY),
        ("system:static_prefix", static_prefix_text(persona)),
        ("system:phone_persona", PHONE_PERSONA_TAIL),
    ]


def _place_pattern(place: str) -> re.Pattern[str]:
    return re.compile(rf"(?i)(?<![A-Za-z]){re.escape(place)}(?![A-Za-z])")


def test_tool_schemas_and_system_prompt_do_not_name_bench_places() -> None:
    """A schema example that repeats a bench city is an answer hint."""
    places = bench_place_names()
    assert places, "bench and eval data yielded no city or place"
    # The loader has to see the matrix weather city or this guard is hollow.
    assert "Springfield" in places
    assert "Illinois" in places
    leaks: list[str] = []
    for label, text in [*_tool_schema_texts(), *_system_prompt_texts()]:
        for place in sorted(places):
            if _place_pattern(place).search(text):
                leaks.append(f"{place} in {label}")
    assert not leaks, (
        "a tool schema or the system prompt names a bench city or place:\n"
        + "\n".join(leaks)
    )
