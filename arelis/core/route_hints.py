"""Auto-routing heuristics. Same patterns as before; one home, with tests.

Tool-shaped asks stay on fast because that path follows the tool schema
far more reliably than a long research loop, which tends to narrate a
call instead of emitting one. Deep / heavy research only → 14b. Short
factual "look this up" stays on fast. Bare "research" / "cite" alone
no longer force a VRAM swap (H2).

This module does not pick a model. Orchestrator.classify_role still
owns chip vs hint vs default.
"""

from __future__ import annotations

import re

TOOL_LOOP_HINT = re.compile(
    r"\b(search|web_search|google|scrape|fetch|open|read|list|write|edit"
    r"|analyze|workspace|web_fetch|file|email|inbox|mail|schedule"
    r"|weather|forecast|recall|remember|agenda|calendar|tasks?|todo"
    r"|git|sms|text|inbound|research(?:_report)?|doc_extract|pdf)\b|https?://",
    re.IGNORECASE,
)
FILE_LOOP_HINT = re.compile(
    r"\b(file|readme|path|workspace|edit|write|refactor|python|code|debug"
    r"|class|function|lint|git|branch|commit|diff)\b",
    re.IGNORECASE,
)
RESEARCH_HINTS: list[re.Pattern[str]] = [
    re.compile(
        r"\b("
        r"deep\s*-?\s*dive|"
        r"deeply\s+research|"
        r"deep\s+research|"
        r"multi\s*-?\s*source|"
        r"write\s+a\s+report|"
        r"thorough\s+research|"
        r"in\s*-?\s*depth\s+(?:research|look|analysis|report)|"
        r"investigate|"
        r"hypothesis|"
        r"derive|"
        r"astrophys|interferom|spectrum|"
        r"research\s+report|"
        r"cite\s+sources"
        r")\b",
        re.IGNORECASE,
    ),
]


def is_research_hint(text: str) -> bool:
    return any(pattern.search(text) for pattern in RESEARCH_HINTS)


def is_tool_loop(text: str) -> bool:
    return bool(TOOL_LOOP_HINT.search(text))


def is_file_loop(text: str) -> bool:
    return bool(FILE_LOOP_HINT.search(text))
