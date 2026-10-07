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
        r"astrophys|interferom|spectrum|"
        r"research\s+report|"
        r"cite\s+sources"
        r")\b",
        re.IGNORECASE,
    ),
]

# A file they still have to gather. Either half alone stays on fast:
# "write the result as a PDF" of text already in the chat, or
# "search the web for lithium prices".
_FILE_DELIVERABLE = re.compile(
    r"(?i)(?:"
    r"\b(?:write|put|save|export)\b.{0,48}\bas\s+(?:a\s+|an\s+)?pdf\b|"
    r"\bput\s+the\s+(?:report|result)\s+in\s+the\s+file\b|"
    r"\b(?:create|make|write|generate|export|draft)\s+"
    r"(?:(?:me\s+)?(?:a\s+|an\s+|the\s+)?)?"
    r"(?:pdf|docx|xlsx|csv|spreadsheet|workbook|"
    r"word\s+doc(?:ument)?|markdown(?:\s+file)?|text\s+file)\b"
    r")"
)
_OPEN_SOURCES = re.compile(
    r"(?i)\b(?:"
    r"search\s+the\s+web|"
    r"open\s+the\s+(?:papers|pages|sources)|"
    r"research\s+(?:what|how|why|whether)"
    r")\b"
)


def is_sourced_file_ask(text: str) -> bool:
    raw = text or ""
    return bool(_FILE_DELIVERABLE.search(raw) and _OPEN_SOURCES.search(raw))


def is_research_hint(text: str) -> bool:
    if is_sourced_file_ask(text):
        return True
    return any(pattern.search(text) for pattern in RESEARCH_HINTS)


# A question about the world. "ready?" is not one. "what did they measure" is.
_FACT_ASK = re.compile(
    r"(?i)\b("
    r"what|who|when|where|why|how|which|"
    r"explain|compare|measure|measured|find|search|look\s+up|"
    r"paper|papers|source|sources|cite|report"
    r")\b"
)


def research_chip_needs_a_page(text: str) -> bool:
    """The research chip is not itself a warrant.

    A check-in does not need a retrieved page. A sourced file, a deep
    dive, or an actual question does.
    """
    from arelis.core.utterance_guards import looks_like_chat_turn

    raw = text or ""
    if looks_like_chat_turn(raw):
        return False
    if is_research_hint(raw):
        return True
    return bool(_FACT_ASK.search(raw))


def is_tool_loop(text: str) -> bool:
    return bool(TOOL_LOOP_HINT.search(text))


def is_file_loop(text: str) -> bool:
    return bool(FILE_LOOP_HINT.search(text))
