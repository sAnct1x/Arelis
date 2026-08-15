"""Durable tool-routing lessons (ACE playbook items).

These are not facts about the user. They are short, itemized tactics distilled
from real failure modes (permission theater, title-as-URL, weather via scrape,
chat-instead-of-send_sms). Injected only when tags match the turn — never a
full rewrite of the system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arelis.config import PROJECT_ROOT

DEFAULT_LESSONS_PATH = PROJECT_ROOT / "data" / "lessons.yaml"

# Shipped with the repo. data/lessons.yaml can extend or override by id.
_SEED: list[dict[str, Any]] = [
    {
        "id": "no-permission-theater",
        "tags": ["web", "weather", "sms", "email", "workspace", "general"],
        "text": (
            "Never ask whether to proceed when the ask is already clear. "
            "Call the tool; Allow cards handle dangerous side effects."
        ),
    },
    {
        "id": "weather-not-scrape",
        "tags": ["weather"],
        "text": (
            "Weather questions use the weather tool only — never AccuWeather, "
            "weather.com, or hand-built Open-Meteo URLs."
        ),
    },
    {
        "id": "sms-call-not-chat",
        "tags": ["sms"],
        "text": (
            "When who and what to text are known, call send_sms immediately. "
            "Talking about the text does not send it; the confirm card does."
        ),
    },
    {
        "id": "search-url-not-title",
        "tags": ["web"],
        "text": (
            "After web_search, scrape using the URL: line exactly (must start "
            "with http). Never pass the Title: line as url."
        ),
    },
    {
        "id": "scrape-before-answer-news",
        "tags": ["web"],
        "text": (
            "For news or current events, do not answer from search snippets "
            "alone — scrape the best hit first."
        ),
    },
    {
        "id": "no-fake-side-effects",
        "tags": ["sms", "email", "workspace", "general"],
        "text": (
            "Never claim you sent, wrote, deleted, or remembered something "
            "unless a tool result this turn shows success."
        ),
    },
    {
        "id": "scrape-fail-stop-loop",
        "tags": ["web"],
        "text": (
            "If scrape or web_fetch fails on a URL, try at most one alternate "
            "(AMP/print sibling or a different search hit). Do not hammer the "
            "same dead URL; then answer with what you have and say the page failed."
        ),
    },
    {
        "id": "search-fail-say-so",
        "tags": ["web"],
        "text": (
            "If web_search returns an error, say search failed and stop inventing "
            "headlines. Do not chain scrape on URLs you never successfully found."
        ),
    },
    {
        "id": "recall-miss-is-ok",
        "tags": ["general", "workspace"],
        "text": (
            "A failed or empty recall is a miss, not permission to invent. "
            "Say you do not have it indexed, or ask a clarifying question."
        ),
    },
    {
        "id": "math-use-calculator",
        "tags": ["general"],
        "text": (
            "Numeric and percentage questions must call calculator. "
            "Never invent arithmetic from memory."
        ),
    },
    {
        "id": "routing-gap-call-tools",
        "tags": ["web", "general"],
        "text": (
            "When tools are expected for the ask, call those tools now. "
            "Do not narrate what you would do instead of tool use."
        ),
    },
]


@dataclass(frozen=True)
class Lesson:
    id: str
    tags: tuple[str, ...]
    text: str


def _parse_lesson(raw: dict[str, Any]) -> Lesson | None:
    lid = str(raw.get("id") or "").strip()
    text = str(raw.get("text") or "").strip()
    if not lid or not text:
        return None
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tag_t = (tags,)
    else:
        tag_t = tuple(str(t).strip() for t in tags if str(t).strip())
    return Lesson(id=lid, tags=tag_t or ("general",), text=text)


_lessons_cache: list[Lesson] | None = None
_lessons_cache_key: tuple[str, float | None] | None = None


def invalidate_lessons_cache() -> None:
    """Drop the process-local lessons cache (e.g. after mine append)."""
    global _lessons_cache, _lessons_cache_key
    _lessons_cache = None
    _lessons_cache_key = None


def load_lessons(path: Path | None = None) -> list[Lesson]:
    """Seed lessons plus optional overrides from data/lessons.yaml.

    Cached by path + mtime so every agent turn does not re-parse YAML.
    """
    global _lessons_cache, _lessons_cache_key
    path = path or DEFAULT_LESSONS_PATH
    mtime = path.stat().st_mtime if path.is_file() else None
    key = (str(path.resolve()) if path.exists() else str(path), mtime)
    if _lessons_cache is not None and _lessons_cache_key == key:
        return list(_lessons_cache)

    by_id: dict[str, Lesson] = {}
    for raw in _SEED:
        lesson = _parse_lesson(raw)
        if lesson:
            by_id[lesson.id] = lesson
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        items = data.get("lessons") if isinstance(data, dict) else data
        if isinstance(items, list):
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                lesson = _parse_lesson(raw)
                if lesson:
                    by_id[lesson.id] = lesson
    loaded = list(by_id.values())
    _lessons_cache = loaded
    _lessons_cache_key = key
    return list(loaded)


def select_lessons(
    *,
    skill_ids: list[str],
    preflight_kinds: list[str] | None = None,
    user_text: str = "",
    max_lessons: int = 4,
    path: Path | None = None,
) -> list[Lesson]:
    """Pick lessons whose tags overlap this turn's skills / intents."""
    tags: set[str] = set(skill_ids)
    for kind in preflight_kinds or []:
        if kind == "sms_send":
            tags.add("sms")
        elif kind == "weather":
            tags.add("weather")
    lowered = (user_text or "").lower()
    if any(w in lowered for w in ("search", "news", "latest", "article", "http")):
        tags.add("web")
    if not tags:
        tags.add("general")

    scored: list[tuple[int, Lesson]] = []
    for lesson in load_lessons(path):
        overlap = len(tags.intersection(lesson.tags))
        if overlap or "general" in lesson.tags:
            # Prefer specific overlap; general is a weak match.
            score = overlap * 10 + (1 if "general" in lesson.tags else 0)
            if overlap or tags == {"general"}:
                scored.append((score, lesson))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    # Drop pure-general fillers when we already have specific lessons.
    out: list[Lesson] = []
    for score, lesson in scored:
        if len(out) >= max_lessons:
            break
        if score <= 1 and out:
            continue
        out.append(lesson)
    return out[:max_lessons]


def format_lessons(lessons: list[Lesson]) -> str | None:
    if not lessons:
        return None
    lines = ["## Lessons from past failures (follow these)"]
    for lesson in lessons:
        lines.append(f"- ({lesson.id}) {lesson.text}")
    return "\n".join(lines)
