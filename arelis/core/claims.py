"""Deterministic exactness detectors — math asks and contingent fact asks.

These are not NLI. They are narrow pattern gates so a 7B cannot finish a turn
with bare arithmetic or unsupported news/weather/"you told me" claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arelis.core.intent_catalog import exactness_match

# Clear arithmetic / percentage / "what is X of Y" — must use calculator.
# Bare "x" as multiply needs spaces (filenames like beam-1965x1106.png are NOT math).
_MATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:what\s+is|what's|calculate|compute|how\s+much\s+is)\b.{0,40}?"
        r"(?:\d|percent|%|\+|minus|times|divided)",
        re.I | re.S,
    ),
    re.compile(r"\b\d+(?:\.\d+)?\s*%\s+of\s+\d+", re.I),
    re.compile(
        r"\b(?:\d+(?:\.\d+)?)\s*"
        r"(?:\+|plus|-|minus|times|\*|\u00d7|/|divided\s+by)\s*"
        r"(?:\d+(?:\.\d+)?)\b",
        re.I,
    ),
    # "17 x 19" / "3 x 4" — spaces required so image dims (1965x1106) never match.
    re.compile(
        r"\b(?:\d+(?:\.\d+)?)\s+x\s+(?:\d+(?:\.\d+)?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:square\s+root|sqrt|factorial|mod(?:ulo)?)\b.{0,30}\d",
        re.I | re.S,
    ),
)

# Integrals / derivatives are not calculator arithmetic — do not force calc.
_SYMBOLIC_MATH = re.compile(
    r"(?i)\b("
    r"integral|integrate|antiderivative|"
    r"derivative|differentiate|differentiating|"
    r"d/dx|partial\s+derivative|"
    r"limit\s+as|symbolic"
    r")\b"
)

# High-precision contingent asks that need a tool warrant this turn.
_NEWS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:news|headline|breaking|latest\s+(?:on|about)|what\s+did\s+\w+\s+say)\b",
        re.I,
    ),
    re.compile(r"\b(?:according\s+to|article|wsj|nytimes|reuters|bbc)\b", re.I),
)
_PRICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:price|stock\s+price|how\s+much\s+does|cost\s+of|trading\s+at)\b",
        re.I,
    ),
)
# PDF / local-doc quote asks — narrow; avoid "what is a PDF?" definitional hits.
_DOC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bwhat\s+does\s+(?:this|the|my|\S+\.pdf)\s+"
        r"(?:pdf|document|file|contract|quote)\s+say\b",
        re.I,
    ),
    re.compile(
        r"\bwhat\s+does\s+\S+\.pdf\s+say\b",
        re.I,
    ),
    re.compile(
        r"\b(?:quote|extract|read|pull)\s+(?:from|out\s+of)\s+"
        r"(?:the\s+|this\s+|my\s+)?(?:pdf|document)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:pdf|document)\s+say\s+about\b",
        re.I,
    ),
)
# Calendar / agenda asks — prefer agenda tool warrant (not briefing invent).
_AGENDA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bwhat(?:'s|\s+is)\s+on\s+(?:my\s+)?"
        r"(?:calendar|agenda)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:anything|any(?:thing)?)\s+on\s+(?:my\s+)?"
        r"(?:calendar|agenda)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:meetings?|events?)\s+"
        r"(?:today|tomorrow|this\s+(?:week|morning|afternoon))\b",
        re.I,
    ),
    re.compile(
        r"\b(?:check|look\s+at|show(?:\s+me)?)\s+(?:my\s+)?"
        r"(?:calendar|agenda)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:create|add|schedule|set)\s+(?:an?\s+)?"
        r"(?:calendar\s+)?(?:event|meeting|appointment|reminder)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:add\s+to\s+(?:my\s+)?calendar|calendar\s+event|"
        r"put\s+(?:this\s+)?on\s+(?:my\s+)?calendar)\b",
        re.I,
    ),
)
# Git status/diff/log asks — need git_info warrant (not inventing branch state).
_GIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:what(?:'s|\s+is)|show(?:\s+me)?|check|get)\s+"
        r"(?:the\s+)?(?:git\s+)?(?:status|diff|log)\b",
        re.I,
    ),
    re.compile(
        r"\bgit\s+(?:status|diff|log)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:working\s+tree|uncommitted|dirty\s+(?:tree|repo|state)|"
        r"current\s+branch)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:branch|repo|repository)\s+(?:status|state|clean|dirty)\b",
        re.I,
    ),
)
# Local to-do / checklist asks — need tasks warrant.
_TASKS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:what(?:'s|\s+are)|show(?:\s+me)?|list|check)\s+"
        r"(?:my\s+)?(?:open\s+)?(?:tasks?|to-?dos?|checklist)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:tasks?|to-?dos?)\s+(?:do\s+i\s+have|open|left|remaining)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:add|create)\s+(?:a\s+)?(?:task|to-?do)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:mark|complete|finish|done)\s+(?:the\s+|my\s+)?"
        r"(?:task|to-?do)\b",
        re.I,
    ),
    re.compile(
        r"\bwhat(?:'s|\s+is)\s+on\s+(?:my\s+)?(?:todo|to-do|task)\s+list\b",
        re.I,
    ),
)
# Durable goals/commitments — need goals warrant (not inventing outcomes).
# Avoid bare "commit" (git) and definitional "what is a goal?".
_GOALS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:what(?:'s|\s+are)|show(?:\s+me)?|list)\s+"
        r"(?:my\s+)?(?:goals?|commitments?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:am\s+i\s+committed\s+to|what\s+am\s+i\s+(?:working\s+toward|"
        r"committed\s+to))\b",
        re.I,
    ),
    re.compile(
        r"\b(?:add|set|create)\s+(?:a\s+)?(?:goal|commitment)\b",
        re.I,
    ),
    re.compile(
        r"\bcommit\s+to\b",
        re.I,
    ),
    re.compile(
        r"\b(?:drop|pause|resume)\s+(?:that\s+|the\s+|my\s+)?"
        r"(?:goal|commitment)\b",
        re.I,
    ),
)
# Local table / CSV asks — need analyze warrant (not inventing stats).
_ANALYZE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"[^\s\"']+\.(?:csv|xlsx|xls|tsv|tab|json)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:csv|xlsx|xls|tsv|spreadsheet|dataframe|excel)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:summarize|analyze|describe)\b.{0,48}\b(?:data|table|sheet)\b",
        re.I | re.S,
    ),
)

# Answer-side: claimed send success (finish-path honesty, not ask detection).
# Soft paraphrases ("I've sent it", "it's on its way") must still refuse without
# a send_* warrant — otherwise 7B narrates success past Allow / SMTP failure.
_SEND_SUCCESS_CLAIM = re.compile(
    r"(?i)\b(?:"
    r"i\s+(?:just\s+|have\s+|ve\s+)?(?:texted|emailed)\b|"
    r"i(?:'|\u2019)?ve\s+(?:just\s+)?(?:texted|emailed|sent)\b|"
    r"i\s+(?:just\s+|have\s+)?sent\s+(?:the\s+|your\s+|it\s+|that\s+)?"
    r"(?:text|sms|message|email|mail|it|that)?\b|"
    r"(?:the\s+)?(?:text|sms|email|mail|message)\s+(?:has\s+been\s+|was\s+)?sent\b|"
    r"(?:the\s+)?(?:text|sms|email|mail|message)\s+went\s+(?:out|through)\b|"
    r"successfully\s+sent\s+(?:the\s+)?(?:text|sms|email|mail|message)\b|"
    r"i\s+(?:have\s+)?already\s+sent\s+(?:the\s+)?(?:text|sms|message|email|mail|it)\b|"
    r"(?:it(?:'|\u2019)?s|that(?:'|\u2019)?s)\s+on\s+(?:its|the)\s+way\b|"
    r"(?:done|all\s+set)[\u2014\-\u2013,.\s]+(?:i\s+)?(?:sent|emailed|texted)\b|"
    r"(?:brian|they|he|she)\s+(?:has|have|got)\s+(?:it|the\s+(?:email|text|message))\b|"
    r"(?:email|text|sms|message)\s+(?:is|was)\s+(?:out|delivered|on\s+(?:its|the)\s+way)\b|"
    # Narrated success without a tool warrant (7B soft paraphrases).
    r"(?:i\s+)?(?:went\s+ahead\s+and\s+)?(?:sent|emailed|texted)\s+(?:it|that|them|him|her)\b|"
    r"(?:your\s+)?(?:email|text|message)\s+(?:should\s+be|is)\s+(?:in\s+their\s+inbox|sent)\b"
    r")"
)
_SEND_SMS_CLAIM = re.compile(
    r"(?i)\b(?:texted|sms|text\s+(?:has\s+been\s+|was\s+)?sent|"
    r"sent\s+(?:the\s+)?(?:text|sms)|"
    r"(?:text|sms)\s+(?:is|was)\s+(?:out|delivered|on\s+(?:its|the)\s+way))\b"
)
_SEND_EMAIL_CLAIM = re.compile(
    r"(?i)\b(?:emailed|email\s+(?:has\s+been\s+|was\s+)?sent|"
    r"sent\s+(?:the\s+)?(?:email|mail)|"
    r"(?:email|mail)\s+(?:is|was)\s+(?:out|delivered|on\s+(?:its|the)\s+way))\b"
)


# Urgency / attention asks — need attention warrant (not inventing urgency).
_ATTENTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:what\s+needs\s+(?:my\s+)?attention|"
        r"what(?:'s|\s+is)\s+(?:urgent|due\s+soon)|"
        r"anything\s+(?:urgent|overdue)|"
        r"what\s+should\s+i\s+(?:focus\s+on|prioritize))\b",
        re.I,
    ),
)

# Visual ask-shapes — need a vision warrant (not inventing screenshot contents).
_VISION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:what(?:'s|\s+is)\s+in|describe|look\s+at|see)\s+"
        r"(?:(?:this|the|that|your)\s+)?"
        r"(?:image|screenshot|photo|diagram|picture)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:image|screenshot|photo|diagram)\b.{0,40}"
        r"(?:show|contain|depict|look\s+like)\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:outputs[/\\]images[/\\]|outputs/images/)\S+\.(?:png|jpe?g|webp|gif)\b",
        re.I,
    ),
    re.compile(
        r"(?i)\b(?:describe|look\s+at)\s+(?:(?:this|the|that)\s+)?"
        r"(?:image|picture|photo|puppy).{0,40}"
        r"(?:you\s+)?(?:just\s+)?(?:generated|made|created|drew|saved)\b",
    ),
)


@dataclass(frozen=True)
class ExactnessNeed:
    needs_calculator: bool
    needs_web_evidence: bool
    needs_weather: bool
    needs_recall: bool
    needs_inbox: bool = False
    needs_inbound_sms: bool = False
    needs_doc: bool = False
    needs_agenda: bool = False
    needs_git: bool = False
    needs_tasks: bool = False
    needs_goals: bool = False
    needs_attention: bool = False
    needs_analyze: bool = False
    needs_vision: bool = False
    kinds: tuple[str, ...] = ()


def detect_math_ask(text: str) -> bool:
    lowered = (text or "").strip()
    if not lowered:
        return False
    if _SYMBOLIC_MATH.search(lowered):
        return False
    return any(p.search(lowered) for p in _MATH_PATTERNS)


def detect_inbox_ask(text: str) -> bool:
    raw = text or ""
    if not raw.strip():
        return False
    # Definitional: "what is an inbox / what does inbox mean"
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?inbox\b", raw, re.I):
        return False
    return exactness_match("inbox", raw)


def detect_inbound_sms_ask(text: str) -> bool:
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?(?:text|sms)\b", raw, re.I):
        return False
    return exactness_match("inbound_sms", raw)


def detect_doc_ask(text: str) -> bool:
    """True for narrow PDF/quote-from-document ask-shapes."""
    raw = text or ""
    if not raw.strip():
        return False
    # Require article so "what does foo.pdf say" is not treated as definitional.
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:a|an)\s+(?:pdf|document)\b", raw, re.I):
        return False
    return any(p.search(raw) for p in _DOC_PATTERNS)


def detect_agenda_ask(text: str) -> bool:
    """True for calendar/agenda ask-shapes that need an agenda warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?(?:calendar|agenda)\b", raw, re.I):
        return False
    return any(p.search(raw) for p in _AGENDA_PATTERNS)


def detect_git_ask(text: str) -> bool:
    """True for git status/diff/log ask-shapes that need a git_info warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:a\s+)?git\b", raw, re.I):
        return False
    return any(p.search(raw) for p in _GIT_PATTERNS)


def detect_tasks_ask(text: str) -> bool:
    """True for to-do/checklist ask-shapes that need a tasks warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?(?:task|to-?do)\b", raw, re.I):
        return False
    return any(p.search(raw) for p in _TASKS_PATTERNS)


def detect_goals_ask(text: str) -> bool:
    """True for goals/commitments ask-shapes that need a goals warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(
        r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?(?:goal|commitment)\b",
        raw,
        re.I,
    ):
        return False
    # Bare git "commit" without "to" / goal language — not a goals ask.
    if re.search(r"\bgit\b", raw, re.I) and not re.search(
        r"\b(?:goal|commitment|commit\s+to)\b", raw, re.I
    ):
        return False
    return any(p.search(raw) for p in _GOALS_PATTERNS)


def detect_analyze_ask(text: str) -> bool:
    """True for local table/CSV ask-shapes that need an analyze warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(
        r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?"
        r"(?:csv|spreadsheet|dataframe|excel|tsv)\b",
        raw,
        re.I,
    ):
        return False
    # Emailing an xlsx/csv is compose, not analyze.
    from arelis.core.email_complete import looks_like_compose_email

    if looks_like_compose_email(raw):
        return False
    # Path correction ("the file is located at C:\\…\\file.xlsx") is not a
    # request to summarize the table.
    if re.search(
        r"(?i)\b("
        r"(?:file|path|document)\s+(?:is\s+)?(?:located\s+)?at|"
        r"here(?:'s|\s+is)\s+the\s+(?:file|path)|"
        r"use\s+this\s+(?:file|path)|"
        r"correct\s+path"
        r")\b",
        raw,
    ):
        return False
    return any(p.search(raw) for p in _ANALYZE_PATTERNS)


def detect_attention_ask(text: str) -> bool:
    """True for urgency ask-shapes that need an attention warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    return any(p.search(raw) for p in _ATTENTION_PATTERNS)


def detect_vision_ask(text: str) -> bool:
    """True for describe/see-this-image ask-shapes that need a vision warrant."""
    raw = text or ""
    if not raw.strip():
        return False
    # Definitional "what is a screenshot?" — not a see-this ask.
    if re.search(
        r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?"
        r"(?:image|screenshot|photo|diagram|vl|vision)\b",
        raw,
        re.I,
    ):
        return False
    from arelis.core.image_refs import mentions_camera_look
    from arelis.core.look import classify_look

    if mentions_camera_look(raw) or classify_look(raw):
        return True
    return any(p.search(raw) for p in _VISION_PATTERNS)


def detect_send_success_claim(text: str) -> bool:
    """True when the answer asserts an outbound SMS/email already went out."""
    return bool(_SEND_SUCCESS_CLAIM.search(text or ""))


def send_claim_missing_kinds(text: str, *, has_send_sms: bool, has_send_email: bool) -> list[str]:
    """Which send_* warrants a send-success claim still needs."""
    if not detect_send_success_claim(text):
        return []
    raw = text or ""
    sms_shaped = bool(_SEND_SMS_CLAIM.search(raw))
    email_shaped = bool(_SEND_EMAIL_CLAIM.search(raw))
    missing: list[str] = []
    if sms_shaped and not email_shaped:
        if not has_send_sms:
            missing.append("send_sms")
        return missing
    if email_shaped and not sms_shaped:
        if not has_send_email:
            missing.append("send_email")
        return missing
    # Generic "message was sent" — either outbound warrant is enough.
    if not (has_send_sms or has_send_email):
        missing.append("send_sms")
    return missing


def detect_exactness_need(text: str) -> ExactnessNeed:
    """What warrants this user turn requires before a final answer is honest."""
    kinds: list[str] = []
    needs_calc = detect_math_ask(text)
    needs_vision = detect_vision_ask(text)
    # Image-describe turns often include dimensioned filenames (1965x1106.png).
    # Prefer the vision warrant; never force calculator on those asks.
    if needs_vision and needs_calc:
        needs_calc = False
    if needs_calc:
        kinds.append("math")
    needs_web = (
        any(p.search(text or "") for p in _NEWS_PATTERNS)
        or any(p.search(text or "") for p in _PRICE_PATTERNS)
        or exactness_match("research", text)
    )
    if needs_web:
        kinds.append("web")
    needs_weather = exactness_match("weather", text)
    if needs_weather:
        kinds.append("weather")
    needs_recall = exactness_match("recall", text)
    if needs_recall:
        kinds.append("recall")
    needs_inbox = detect_inbox_ask(text)
    if needs_inbox:
        kinds.append("inbox")
    needs_inbound = detect_inbound_sms_ask(text)
    if needs_inbound:
        kinds.append("inbound_sms")
    needs_doc = detect_doc_ask(text)
    if needs_doc:
        kinds.append("doc")
    needs_agenda = detect_agenda_ask(text)
    if needs_agenda:
        kinds.append("agenda")
    needs_git = detect_git_ask(text)
    if needs_git:
        kinds.append("git")
    needs_tasks = detect_tasks_ask(text)
    if needs_tasks:
        kinds.append("tasks")
    needs_goals = detect_goals_ask(text)
    if needs_goals:
        kinds.append("goals")
    needs_attention = detect_attention_ask(text)
    if needs_attention:
        kinds.append("attention")
    needs_analyze = detect_analyze_ask(text)
    if needs_analyze:
        kinds.append("analyze")
    if needs_vision:
        kinds.append("vision")
    return ExactnessNeed(
        needs_calculator=needs_calc,
        needs_web_evidence=needs_web,
        needs_weather=needs_weather,
        needs_recall=needs_recall,
        needs_inbox=needs_inbox,
        needs_inbound_sms=needs_inbound,
        needs_doc=needs_doc,
        needs_agenda=needs_agenda,
        needs_git=needs_git,
        needs_tasks=needs_tasks,
        needs_goals=needs_goals,
        needs_attention=needs_attention,
        needs_analyze=needs_analyze,
        needs_vision=needs_vision,
        kinds=tuple(kinds),
    )


_CALC_FORCE_NOTICE = (
    "Exactness: this question needs a precise numeric answer. "
    "Call the calculator tool now with the expression. "
    "Do not invent the number from memory."
)

_EVIDENCE_FORCE_NOTICE = (
    "Exactness: you are about to assert a contingent fact without a warrant "
    "from this turn's tools. Call the required tool now "
    "(weather, web_search+scrape, recall, inbox, inbound_sms, "
    "doc_extract, agenda, git_info, tasks, goals, analyze, or vision), "
    "or say you do not know. "
    "Do not guess."
)


def math_force_notice() -> str:
    return _CALC_FORCE_NOTICE


def evidence_force_notice() -> str:
    return _EVIDENCE_FORCE_NOTICE


def weather_force_notice() -> str:
    """One-shot nudge when a weather ask never called the weather tool."""
    return (
        "This turn asks about the weather/forecast/temperature outside. "
        "Call the weather tool now (omit lat/lon unless they named another place). "
        "Do not web_search or scrape AccuWeather/weather.com. Do not invent a forecast."
    )


_TITLED = re.compile(r"(?i)(?:titled|called|named)\s+[\"']?(.+?)[\"']?\s*$")
_STORE_ID = re.compile(r"#(?P<id>\d+)")


def _last_store_id(text: str, *, kind: str) -> str:
    """Best id from this utterance (`#6` / `id 6`). kind is unused hint."""
    del kind
    match = _STORE_ID.search(text or "")
    if match:
        return match.group("id")
    bare = re.search(r"(?i)\bid\s*[#=]?\s*(\d+)\b", text or "")
    if bare:
        return bare.group(1)
    return ""


def last_store_ids_from_context(
    history: list[Any] | None = None,
    receipts: list[Any] | None = None,
) -> list[str]:
    """Goal/task ids from recent receipts or `#N` lines in chat."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        val = str(raw or "").strip()
        if val.startswith("id="):
            val = val[3:]
        if val.isdigit() and val not in seen:
            seen.add(val)
            found.append(val)

    for rec in reversed(receipts or []):
        if not isinstance(rec, dict):
            continue
        action = str(rec.get("action") or "")
        tool = str(rec.get("tool") or "")
        if tool not in {"goals", "tasks"} and not action.startswith(
            ("goals.", "tasks.")
        ):
            continue
        for item in rec.get("ids") or []:
            _add(str(item))
        if rec.get("id") is not None:
            _add(str(rec.get("id")))
        if found:
            return found
    for item in reversed(history or []):
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        blob = str(content or "")
        hits = _STORE_ID.findall(blob)
        if hits:
            for hit in hits:
                _add(hit)
            if found:
                return found
    return found


def local_store_inject_args(
    tool: str,
    text: str,
    *,
    receipts: list[Any] | None = None,
    history: list[Any] | None = None,
) -> dict[str, str]:
    """Deterministic tasks/goals args when the 7B never called the tool."""
    raw = (text or "").strip()
    titled = ""
    match = _TITLED.search(raw)
    if match:
        titled = match.group(1).strip().rstrip(".! ")
    if tool == "tasks":
        if re.search(r"(?i)\b(?:add|create)\s+(?:a\s+)?(?:task|to-?do)\b", raw):
            return {"action": "add", "title": titled or "untitled"}
        if re.search(r"(?i)\b(?:delete|remove)\b", raw):
            nid = _last_store_id(raw, kind="task") or (
                last_store_ids_from_context(history, receipts) or [""]
            )[0]
            if nid:
                return {"action": "remove", "id": nid}
        return {"action": "list"}
    if tool == "goals":
        if re.search(r"(?i)\b(?:add|set|create)\s+(?:a\s+)?(?:goal|commitment)\b", raw):
            return {"action": "add", "title": titled or "untitled"}
        if re.search(r"(?i)\b(?:delete|remove|drop)\b", raw):
            nid = _last_store_id(raw, kind="goal") or (
                last_store_ids_from_context(history, receipts) or [""]
            )[0]
            if nid:
                return {"action": "remove", "id": nid}
        return {"action": "list"}
    if tool == "memory":
        if re.search(r"(?i)\bforget\b", raw):
            fact = re.sub(
                r"(?i)^.*?\bforget\s+(?:that\s+)?", "", raw
            ).strip().rstrip(".!")
            return {"action": "forget", "fact": fact or raw}
        fact = re.sub(
            r"(?i)^.*?\bremember\s+(?:that\s+)?", "", raw
        ).strip().rstrip(".!")
        return {"action": "remember", "fact": fact or raw}
    if tool == "contacts":
        who = contact_who_from_text(raw)
        return {"action": "get", "who": who or "wife"}
    return {"action": "list"}


def lock_memory_forget_args(args: dict[str, Any], text: str) -> dict[str, Any]:
    """Overwrite forget fact= from the user utterance. Ignore leftover key/value."""
    out = dict(args)
    locked = local_store_inject_args("memory", text)
    fact = str(locked.get("fact") or "").strip()
    if fact:
        out["action"] = "forget"
        out["fact"] = fact
        out.pop("key", None)
        out.pop("value", None)
    return out


# The possessive is optional and so is its apostrophe. Dictation does not type
# one, so "what is my wifes phone number" has to resolve the same as
# "my wife's" — before this the trailing s defeated the word boundary and the
# alias came back empty, which reads as "I don't know who your wife is".
_CONTACT_WHO = re.compile(
    r"(?i)\b(?:who\s+is\s+my\s+|my\s+)"
    r"(?P<who>wife|husband|mom|mother|dad|father|brother|sister|"
    r"daughter|son)(?:['\u2019]?s)?\b"
)


def contact_who_from_text(text: str) -> str:
    """Alias to look up from 'who is my wife' / 'my daughter' phrasing."""
    match = _CONTACT_WHO.search(text or "")
    if match:
        return (match.group("who") or "").strip().lower()
    return ""


_REFUSAL_MARKERS: tuple[str, ...] = (
    "i don't know",
    "i do not know",
    "cannot compute",
    "can't compute",
    "unable to calculate",
    "no evidence",
    "could not find",
    "don't have that",
    "do not have that",
    "not indexed",
    "search failed",
    "page failed",
    "was not sent",
    "not sent",
    "haven't sent",
    "have not sent",
)

# "I don't know X, but here's an invented claim…" is not a refusal.
_HEDGE_THEN_CLAIM = re.compile(
    r"(?:i don't know|i do not know|could not find|no evidence).{0,100}?\b(?:but|however)\b",
    re.I | re.S,
)


def answer_looks_like_refusal(text: str) -> bool:
    """True when the model already admitted it cannot answer (lead-biased)."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if _HEDGE_THEN_CLAIM.search(lowered):
        return False
    head = lowered[:200]
    if not any(m in head for m in _REFUSAL_MARKERS):
        return False
    # Long answers that keep asserting after a short hedge are not refusals.
    if len(lowered) > 280 and re.search(r"\d", lowered[100:]):
        return False
    return True


# After a successful file read, models sometimes "ack" instead of answering
# ("Got it! I'll keep that in mind…"). That is not a summary.
_ACK_ONLY_MARKERS = (
    "keep that in mind",
    "i'll remember that",
    "i will remember that",
    "feel free to ask",
    "what can i help you with",
    "got it!",
    "noted —",
    "noted.",
)
_ACK_CONTENT_HINTS = (
    "readme",
    "summary",
    "according",
    "the file",
    "it says",
    "it describes",
    "in short",
    "this project",
)


def answer_looks_like_ack_only(text: str) -> bool:
    """True for short acknowledgment replies that dodge the asked question."""
    lowered = (text or "").strip().lower()
    if not lowered or len(lowered) > 320:
        return False
    if not any(m in lowered for m in _ACK_ONLY_MARKERS):
        return False
    return not any(h in lowered for h in _ACK_CONTENT_HINTS)


def file_answer_force_notice() -> str:
    """One-shot nudge after a file tool when the model only acknowledged."""
    return (
        "You already have file contents from a tool result. Answer the user's "
        "request using that content now in plain prose. Do not call "
        "memory.remember unless they explicitly asked you to store a durable "
        "fact. Do not reply with only an acknowledgment."
    )


def unsupported_exactness_reply(
    missing: list[str],
    *,
    calc_failed: bool = False,
    calc_detail: str = "",
) -> str:
    """Deterministic unknown when a force round still lacks warrants."""
    kinds = [k for k in missing if k]
    if "math" in kinds:
        if calc_failed:
            detail = (calc_detail or "").lower()
            if "division by zero" in detail:
                return (
                    "That's undefined — dividing by zero has no value. "
                    "The calculator reported division by zero."
                )
            return (
                "The calculator couldn't evaluate that. It only does "
                "arithmetic (and a few functions like sqrt, sin, log), "
                "not integrals or symbolic calculus."
            )
        return (
            "I don't know — this needs a calculator result and I don't have a "
            "reliable computed value for it."
        )
    if "web" in kinds:
        return (
            "I don't know — I don't have a retrieved page warrant for that "
            "claim, so I won't invent one."
        )
    if "weather" in kinds:
        return (
            "I don't know — I don't have a weather tool reading for that, "
            "so I won't guess."
        )
    if "recall" in kinds:
        return (
            "I don't know — that isn't in what I can recall from our "
            "conversation right now."
        )
    if "inbox" in kinds:
        return (
            "I don't know — I don't have an inbox reading for that, "
            "so I won't invent what mail arrived."
        )
    if "inbound_sms" in kinds:
        return (
            "I don't know — I don't have an inbound SMS reading for that, "
            "so I won't invent a reply."
        )
    if "doc" in kinds:
        return (
            "I don't know — I don't have a document extract for that PDF, "
            "so I won't invent a quote."
        )
    if "agenda" in kinds:
        return (
            "I don't know — I don't have a calendar reading for that, "
            "so I won't invent meetings."
        )
    if "git" in kinds:
        return (
            "I don't know — I don't have a git_info reading for that, "
            "so I won't invent branch or dirty state."
        )
    if "tasks" in kinds:
        return (
            "I don't know — I don't have a tasks reading for that, "
            "so I won't invent to-dos."
        )
    if "goals" in kinds:
        return (
            "I don't know — I don't have a goals reading for that, "
            "so I won't invent goals or commitments."
        )
    if "attention" in kinds:
        return (
            "I don't know — I haven't read your tasks, goals or calendar this "
            "turn, so I won't invent what is urgent."
        )
    if "analyze" in kinds:
        return (
            "I don't know — I don't have an analyze reading for that table, "
            "so I won't invent row counts or column stats."
        )
    if "vision" in kinds:
        return (
            "I don't know — I don't have a vision reading for that image, "
            "so I won't invent what a screenshot or photo shows."
        )
    if "send_sms" in kinds or "send_email" in kinds:
        return unsupported_send_claim_reply()
    joined = ", ".join(kinds) if kinds else "evidence"
    return f"I don't know — I'm missing required {joined} and won't guess."


def unsupported_send_claim_reply() -> str:
    """Deterministic rewrite when the answer claims send without a warrant."""
    return (
        "That message was not sent — I don't have a successful send confirmation "
        "this turn. If a confirm card is open, use Allow there; otherwise ask me "
        "to send again."
    )
