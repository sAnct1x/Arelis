"""Mine logs/turns.log for tool-failure signatures → curated lesson ids.

This is not an LLM rewriting its own prompt. Signatures map to a fixed catalog
of tactics (same spirit as seed lessons). Safe to run at startup: append-only
by id into data/lessons.yaml, never deletes or invents free-form text.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arelis.core.lessons import (
    DEFAULT_LESSONS_PATH,
    invalidate_lessons_cache,
    load_lessons,
)
from arelis.paths import logs_dir

DEFAULT_TURNS_LOG = logs_dir() / "turns.log"

_TOOL_LINE = re.compile(
    r"\btool\b.*?\bname=(?P<name>[^\s]+).*?\bok=(?P<ok>[01])\b"
)
_DONE_LINE = re.compile(
    r"\bdone\b.*?\bstatus=(?P<status>\S+).*?\brounds=(?P<rounds>\d+)"
    r".*?\btools=(?P<tools>\S+)"
)

# Curated catalog: signature id → lesson payload (written into lessons.yaml).
_CATALOG: dict[str, dict[str, Any]] = {
    "scrape-fail-stop-loop": {
        "id": "scrape-fail-stop-loop",
        "tags": ["web"],
        "text": (
            "If scrape or web_fetch fails on a URL, try at most one alternate "
            "(AMP/print sibling or a different search hit). Do not hammer the "
            "same dead URL; then answer with what you have and say the page failed."
        ),
        "when": "scrape/web_fetch failures dominate recent tool errors",
    },
    "search-fail-say-so": {
        "id": "search-fail-say-so",
        "tags": ["web"],
        "text": (
            "If web_search returns an error, say search failed and stop inventing "
            "headlines. Do not chain scrape on URLs you never successfully found."
        ),
        "when": "web_search ok=0 appears in recent turns",
    },
    "recall-miss-is-ok": {
        "id": "recall-miss-is-ok",
        "tags": ["general", "workspace"],
        "text": (
            "A failed or empty recall is a miss, not permission to invent. "
            "Say you do not have it indexed, or ask a clarifying question."
        ),
        "when": "recall ok=0 appears in recent turns",
    },
    "math-use-calculator": {
        "id": "math-use-calculator",
        "tags": ["general"],
        "text": (
            "Numeric and percentage questions must call calculator. "
            "Never invent arithmetic from memory."
        ),
        "when": "exactness math force appears in turns.log",
    },
    "science-use-cas-units": {
        "id": "science-use-cas-units",
        "tags": ["science", "general"],
        "text": (
            "Integrals, derivatives, and ODEs call cas. Conversions and "
            "published constants call units. Charts call plot (Allow). Named "
            "catalogs (arXiv, Horizons, APOD, ADS) call catalog. Never "
            "recite CODATA or a closed form from memory, never fake a "
            "chart in text, and never invent a paper or an ephemeris."
        ),
        "when": "exactness symbolic, units, plot, or catalog force appears in turns.log",
    },
    "routing-gap-call-tools": {
        "id": "routing-gap-call-tools",
        "tags": ["web", "general"],
        "text": (
            "When tools are expected for the ask, call those tools now. "
            "Do not narrate what you would do instead of tool use."
        ),
        "when": "routing_gap appears in turns.log",
    },
}

_EXACTNESS_LINE = re.compile(
    r"\bexactness\b.*?\bgate=(?P<gate>\S+)"
)
_ROUTING_GAP_LINE = re.compile(
    r"\brouting_gap\b.*?\bexpected=(?P<expected>\S+).*?\bused=(?P<used>\S+)"
)


@dataclass(frozen=True)
class MineReport:
    tool_fail_counts: dict[str, int]
    tool_ok_counts: dict[str, int]
    proposed_ids: tuple[str, ...]
    already_present: tuple[str, ...]
    appended_ids: tuple[str, ...]
    lines_scanned: int


def parse_turns_log(
    text: str,
) -> tuple[Counter[str], Counter[str], int, Counter[str], Counter[str]]:
    """Return (fail_counts, ok_counts, lines_scanned, exactness_gates, routing_gaps)."""
    fails: Counter[str] = Counter()
    oks: Counter[str] = Counter()
    exact: Counter[str] = Counter()
    routing: Counter[str] = Counter()
    lines = 0
    for line in text.splitlines():
        lines += 1
        ex = _EXACTNESS_LINE.search(line)
        if ex:
            exact[ex.group("gate")] += 1
        gap = _ROUTING_GAP_LINE.search(line)
        if gap:
            routing["routing_gap"] += 1
        match = _TOOL_LINE.search(line)
        if not match:
            continue
        name = match.group("name")
        if match.group("ok") == "1":
            oks[name] += 1
        else:
            fails[name] += 1
    return fails, oks, lines, exact, routing


def propose_lesson_ids(
    fails: Counter[str],
    *,
    scrape_fail_min: int = 3,
    search_fail_min: int = 1,
    recall_fail_min: int = 1,
    exactness_gates: Counter[str] | None = None,
    routing_gaps: Counter[str] | None = None,
) -> list[str]:
    """Map failure counts to catalog lesson ids (deterministic)."""
    proposed: list[str] = []
    scrape_fails = fails.get("scrape", 0) + fails.get("web_fetch", 0)
    if scrape_fails >= scrape_fail_min:
        proposed.append("scrape-fail-stop-loop")
    if fails.get("web_search", 0) >= search_fail_min:
        proposed.append("search-fail-say-so")
    if fails.get("recall", 0) >= recall_fail_min:
        proposed.append("recall-miss-is-ok")
    gates = exactness_gates or Counter()
    if gates.get("math", 0) >= 1:
        proposed.append("math-use-calculator")
    if (
        gates.get("symbolic", 0) >= 1
        or gates.get("units", 0) >= 1
        or gates.get("plot", 0) >= 1
        or gates.get("catalog", 0) >= 1
    ):
        proposed.append("science-use-cas-units")
    gaps = routing_gaps or Counter()
    if gaps.get("routing_gap", 0) >= 1:
        proposed.append("routing-gap-call-tools")
    return proposed


def _read_tail(path: Path, *, max_bytes: int = 256_000) -> str:
    if not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()  # drop partial first line
        return fh.read().decode("utf-8", errors="replace")


def _load_yaml_lessons(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    items = data.get("lessons") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def append_lessons(
    ids: list[str],
    *,
    path: Path | None = None,
) -> list[str]:
    """Append catalog lessons missing from path. Returns newly written ids."""
    path = path or DEFAULT_LESSONS_PATH
    existing = {str(item.get("id") or "") for item in _load_yaml_lessons(path)}
    # Also skip if already covered by seed/load_lessons (avoid dup injection noise).
    loaded_ids = {lesson.id for lesson in load_lessons(path)}
    to_add: list[dict[str, Any]] = []
    for lid in ids:
        if lid in existing or lid in loaded_ids:
            continue
        entry = _CATALOG.get(lid)
        if not entry:
            continue
        to_add.append(
            {
                "id": entry["id"],
                "tags": list(entry["tags"]),
                "text": entry["text"],
            }
        )
    if not to_add:
        return []

    path.parent.mkdir(parents=True, exist_ok=True)
    prior = _load_yaml_lessons(path)
    merged = prior + to_add
    header = (
        "# Auto-maintained + optional hand edits. Seed lessons live in\n"
        "# arelis/core/lessons.py; entries here replace by id or add new ones.\n"
        "# Generated by arelis.core.lesson_mine / scripts/mine_lessons.py\n"
        "#\n"
    )
    body = yaml.safe_dump({"lessons": merged}, sort_keys=False, allow_unicode=True)
    path.write_text(header + body, encoding="utf-8")
    invalidate_lessons_cache()
    return [str(item["id"]) for item in to_add]


def mine_turns_log(
    *,
    log_path: Path | None = None,
    lessons_path: Path | None = None,
    write: bool = False,
    max_bytes: int = 256_000,
) -> MineReport:
    """Scan turns.log, propose catalog lessons, optionally append to yaml."""
    log_path = log_path or DEFAULT_TURNS_LOG
    lessons_path = lessons_path or DEFAULT_LESSONS_PATH
    text = _read_tail(log_path, max_bytes=max_bytes)
    fails, oks, lines, exact_gates, routing_gaps = parse_turns_log(text)
    proposed = propose_lesson_ids(
        fails, exactness_gates=exact_gates, routing_gaps=routing_gaps
    )
    loaded = {lesson.id for lesson in load_lessons(lessons_path)}
    already = tuple(lid for lid in proposed if lid in loaded)
    appended: list[str] = []
    if write and proposed:
        appended = append_lessons(proposed, path=lessons_path)
    return MineReport(
        tool_fail_counts=dict(fails),
        tool_ok_counts=dict(oks),
        proposed_ids=tuple(proposed),
        already_present=already,
        appended_ids=tuple(appended),
        lines_scanned=lines,
    )
