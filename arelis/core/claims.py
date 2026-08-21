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
# "17 x 19" / "3 x 4". Spaces are required so an unspaced image dimension
# (1965x1106) never matches — which was the whole guard, and it does not hold:
# "1280 x 720 pixels" is how a person writes a size. See _PICTURE_SIZE.
_SPACED_TIMES = re.compile(
    r"\b(?:\d+(?:\.\d+)?)\s+x\s+(?:\d+(?:\.\d+)?)\b",
    re.I,
)

# Words that make a pair of numbers a shape rather than a multiplication. A
# resolution is not a sum, and forcing the calculator onto one ends where it did
# in practice: calculator(expression="1280, 720"), which is not an expression,
# followed by a refusal for a request that had nothing to calculate.
_PICTURE_SIZE = re.compile(
    r"(?i)\b("
    r"px|pixels?|"
    r"thumbnail|resolution|dimensions?|aspect\s+ratio|"
    r"resize|resized|resizing|crop|cropped|"
    r"wallpaper|banner|canvas|"
    r"image|images|photo|photos|picture|pictures|screenshot"
    r")\b"
)

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
    _SPACED_TIMES,
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
    r"limit\s+as|symbolic|"
    r"\bode\b|differential\s+equation|"
    r"closed\s+form"
    r")\b"
)

# Force the CAS — tighter than _SYMBOLIC_MATH so "integrate this with Outlook"
# does not open a SymPy round.
_CAS_FORCE = (
    re.compile(r"(?i)\bintegral\s+of\b"),
    re.compile(r"(?i)\bantiderivative\b"),
    re.compile(r"(?i)\bwhat(?:'s|\s+is)\s+the\s+integral\b"),
    re.compile(
        r"(?i)\bintegrate\s+[a-zA-Z](?:\s|\*\*|\^|\(|$)"
    ),
    re.compile(r"(?i)\bderivative\s+of\b"),
    re.compile(r"(?i)\bdifferentiate\b"),
    re.compile(r"(?i)\bd/dx\b"),
    re.compile(r"(?i)\bpartial\s+derivative\b"),
    re.compile(r"(?i)\b(solve\s+(this\s+|the\s+)?(ode|differential\s+equation))\b"),
    re.compile(r"(?i)\bdifferential\s+equation\b"),
    re.compile(r"(?i)\b\bode\b"),
    re.compile(
        r"(?i)\bsimplify\s+(?:this|the)\s+(?:expression|equation|algebra)\b"
    ),
    re.compile(r"(?i)\bclosed\s+form\b"),
    re.compile(r"(?i)\bcheck\s+the\s+algebra\b"),
    re.compile(r"(?i)\bsymbolic\s+(?:algebra|integral|derivative)\b"),
)

_UNIT_NAMES = (
    r"meters?|metres?|kilometers?|kilometres?|kg|kilograms?|"
    r"feet|foot|inches|inch|pounds?|lbs?|kelvin|celsius|fahrenheit|"
    r"eV|joules?|watts?|newtons?|parsecs?|\bau\b|nm|μm|um|"
    r"solar\s+masses?"
)
_FILE_CONVERT = re.compile(
    r"(?i)\b(file|pdf|docx?|xlsx|csv|mp3|png|jpe?g|video|audio|txt)\b"
)
_UNITS_FORCE = (
    re.compile(
        rf"(?i)\bconvert\b.{{0,48}}\bto\s+(?:{_UNIT_NAMES})\b",
    ),
    re.compile(
        rf"(?i)\b(?:in|into|to)\s+(?:{_UNIT_NAMES})\b",
    ),
    re.compile(r"(?i)\b\d+(?:\.\d+)?\s*(?:ft|feet)\s+\d+(?:\.\d+)?\s*(?:in|inches)\b"),
    re.compile(r"(?i)\bdimensional\s+analysis\b"),
    re.compile(rf"(?i)\bhow\s+many\s+(?:{_UNIT_NAMES})\b"),
)
_CMB_FRAME = re.compile(
    r"(?i)\b(cmb\s+frame|rest\s+frame|comoving)\b"
)
_CONSTANT_FORCE = (
    re.compile(r"(?i)\bgravitational\s+constant\b"),
    re.compile(r"(?i)\bnewtonian\s+constant\b"),
    re.compile(r"(?i)\bspeed\s+of\s+light\b"),
    re.compile(r"(?i)\bplanck(?:'s)?\s+constant\b"),
    re.compile(r"(?i)\bstefan[- ]boltzmann\b"),
    re.compile(r"(?i)\bavogadro(?:'s)?\s+(?:number|constant)\b"),
    re.compile(r"(?i)\bboltzmann\s+constant\b"),
    re.compile(r"(?i)\bhubble\s+constant\b"),
    re.compile(r"(?i)\bastronomical\s+unit\b"),
    re.compile(r"(?i)\bsolar\s+mass\b"),
    re.compile(r"(?i)\bsolar\s+radius\b"),
    re.compile(r"(?i)\bwhat(?:'s|\s+is)\s+(?:the\s+)?(?:value\s+of\s+)?G\b"),
    re.compile(r"(?i)\bCODATA\b"),
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
        r"\b(?:open|pull\s+up|bring\s+up|show)\s+"
        r"(?:(?:me\s+)?(?:the\s+|my\s+)?)?(?:google\s+)?"
        r"(?:calendar|agenda)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:close|hide|dismiss|put\s+away)\s+"
        r"(?:(?:the\s+|my\s+)?)?(?:google\s+)?"
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
        r"put\s+(?:this\s+)?on\s+(?:my\s+)?calendar|"
        r"at\s+an?\s+event\s+for)\b",
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
    needs_cas: bool = False
    needs_units: bool = False
    needs_plot: bool = False
    needs_catalog: bool = False
    needs_document: bool = False
    kinds: tuple[str, ...] = ()


_PLOT_FORCE = (
    re.compile(r"(?i)\bplot\s+(?:this|the|my|it)\b"),
    re.compile(r"(?i)\b(?:scatter|line)\s+plot\b"),
    re.compile(r"(?i)\bplot\s+residuals\b"),
    re.compile(r"(?i)\bfit\s+a\s+line\b"),
    re.compile(r"(?i)\b(?:line|bar|scatter)\s+chart\b"),
    re.compile(r"(?i)\bchart\s+(?:this|the|my)\b"),
    re.compile(r"(?i)\bmake\s+a\s+(?:plot|chart|graph)\b"),
    re.compile(r"(?i)\bshow\s+me\s+a\s+(?:plot|chart|graph)\b"),
    re.compile(r"(?i)\bplot\s+.{0,40}\b(?:csv|tsv|xlsx|spreadsheet|columns?)\b"),
)


def detect_plot_ask(text: str) -> bool:
    """True when the ask wants a chart file, not a movie plot or a garden."""
    raw = text or ""
    if not raw.strip():
        return False
    if re.search(r"(?i)\b(plot\s+twist|movie\s+plot|plot\s+of\s+(?:land|the\s+film))\b", raw):
        return False
    return any(p.search(raw) for p in _PLOT_FORCE)


_DOCUMENT_FORCE = (
    re.compile(
        r"(?i)\b(?:create|make|write|generate|export|draft)\s+"
        r"(?:(?:me\s+)?(?:a\s+|an\s+|the\s+)?)?"
        r"(?:pdf|docx|xlsx|csv|spreadsheet|workbook|"
        r"word\s+doc(?:ument)?|markdown(?:\s+file)?|text\s+file)\b"
    ),
    re.compile(
        r"(?i)\b(?:save|export|download)\s+"
        r"(?:(?:it|this|that|them|the\s+\w+)\s+)?"
        r"(?:as|to)\s+(?:a\s+|an\s+)?"
        r"(?:pdf|docx|xlsx|csv|excel|word|markdown)\b"
    ),
)


def detect_document_ask(text: str) -> bool:
    """True when they want a new file they can open, not a PDF read."""
    raw = text or ""
    if not raw.strip():
        return False
    if detect_doc_ask(raw):
        return False
    return any(p.search(raw) for p in _DOCUMENT_FORCE)


_CATALOG_FORCE = (
    re.compile(r"(?i)\barxiv\b"),
    re.compile(r"(?i)\bpreprints?\b"),
    re.compile(r"(?i)\bjpl\s+horizons\b"),
    re.compile(r"(?i)\bephemeris\b"),
    re.compile(
        r"(?i)\bwhere is (?:mercury|venus|mars|jupiter|saturn|uranus|"
        r"neptune|pluto|the moon)\b.{0,24}\b(tonight|today|now)\b"
    ),
    re.compile(r"(?i)\b(apod|astronomy picture of the day)\b"),
    re.compile(r"(?i)\bnasa'?s? (?:photo|picture) of the day\b"),
    re.compile(r"(?i)\b(nasa\s+ads|adsabs|astrophysics data system)\b"),
    re.compile(r"(?i)\bfind me a paper\b"),
    re.compile(r"(?i)\blook up a paper\b"),
    re.compile(r"(?i)\bpapers on\b"),
    re.compile(r"(?i)\bsearch arxiv\b"),
)

_PAPER_QUERY = re.compile(
    r"(?i)(?:find me a paper|look up a paper|search arxiv|papers?)\s+"
    r"(?:on|about|for)\s+(.+)$"
)


def detect_catalog_ask(text: str) -> bool:
    """True when the ask named a science catalog, not a shopping catalog."""
    raw = text or ""
    if not raw.strip():
        return False
    return any(p.search(raw) for p in _CATALOG_FORCE)


def draft_catalog_args(text: str) -> dict[str, str]:
    """catalog(action=arxiv) from 'find me a paper on …'."""
    raw = " ".join((text or "").split()).strip()
    query = raw
    match = _PAPER_QUERY.search(raw)
    if match:
        query = match.group(1).strip(" ?.!")
    elif re.search(r"(?i)\barxiv\b", raw):
        query = re.sub(r"(?i)\b(?:search\s+)?arxiv(?:\s+for)?\b", " ", raw)
        query = " ".join(query.split()).strip(" ?.!") or raw
    return {"action": "arxiv", "query": query or raw}


def detect_cas_ask(text: str) -> bool:
    """True when a closed form needs the CAS, not the pocket calculator."""
    raw = text or ""
    if not raw.strip():
        return False
    return any(p.search(raw) for p in _CAS_FORCE)


def detect_units_ask(text: str) -> bool:
    """True for unit conversion or published-constant asks.

    File conversions and CMB-frame boosts are not Pint.
    """
    raw = text or ""
    if not raw.strip():
        return False
    if _CMB_FRAME.search(raw):
        return False
    if any(p.search(raw) for p in _CONSTANT_FORCE):
        return True
    if _FILE_CONVERT.search(raw) and not re.search(
        rf"(?i)\b(?:{_UNIT_NAMES})\b", raw
    ):
        return False
    return any(p.search(raw) for p in _UNITS_FORCE)


def detect_math_ask(text: str) -> bool:
    lowered = (text or "").strip()
    if not lowered:
        return False
    if _SYMBOLIC_MATH.search(lowered):
        return False
    hits = [p for p in _MATH_PATTERNS if p.search(lowered)]
    if not hits:
        return False
    # When "N x N" is the only arithmetic shape present and the sentence is
    # plainly about the size of a picture, there is nothing to compute. Narrow on
    # purpose: "what is 17 x 19" still forces the calculator, because that has no
    # picture in it.
    if hits == [_SPACED_TIMES] and _PICTURE_SIZE.search(lowered):
        return False
    return True


def detect_inbox_ask(text: str) -> bool:
    raw = text or ""
    if not raw.strip():
        return False
    # Definitional: "what is an inbox / what does inbox mean"
    if re.search(r"\bwhat\s+(?:is|does)\s+(?:an?\s+)?inbox\b", raw, re.I):
        return False
    from arelis.core.email_complete import looks_like_mailbox_mutate

    if looks_like_mailbox_mutate(raw):
        return True
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
    needs_cas = detect_cas_ask(text)
    needs_units = detect_units_ask(text)
    needs_plot = detect_plot_ask(text)
    needs_catalog = detect_catalog_ask(text)
    needs_document = detect_document_ask(text)
    needs_vision = detect_vision_ask(text)
    # Image-describe turns often include dimensioned filenames (1965x1106.png).
    # Prefer the vision warrant; never force calculator on those asks.
    if needs_vision and needs_calc:
        needs_calc = False
    if needs_cas:
        needs_calc = False
        needs_units = False
    if needs_calc and needs_units:
        # "17% of 240 in a table" is arithmetic, not Pint — unless they
        # clearly named a physical unit conversion.
        if not any(p.search(text or "") for p in _UNITS_FORCE[:1]):
            needs_units = False
    if needs_calc:
        kinds.append("math")
    if needs_cas:
        kinds.append("symbolic")
    if needs_units:
        kinds.append("units")
    if needs_plot:
        kinds.append("plot")
    if needs_catalog:
        kinds.append("catalog")
    if needs_document:
        kinds.append("document")
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
        needs_cas=needs_cas,
        needs_units=needs_units,
        needs_plot=needs_plot,
        needs_catalog=needs_catalog,
        needs_document=needs_document,
        kinds=tuple(kinds),
    )


_CALC_FORCE_NOTICE = (
    "Exactness: this question needs a precise numeric answer. "
    "Call the calculator tool now with the expression. "
    "Do not invent the number from memory."
)

_CAS_FORCE_NOTICE = (
    "Exactness: this question needs a closed form from the CAS. "
    "Call the cas tool now (integrate, diff, simplify, solve, or dsolve). "
    "Do not recite an integral or ODE solution from memory."
)

_UNITS_FORCE_NOTICE = (
    "Exactness: this question needs a unit conversion or a published constant. "
    "Call the units tool now (action=convert or action=constant). "
    "Do not recite CODATA or convert by vibe."
)

_PLOT_FORCE_NOTICE = (
    "Exactness: this question needs a chart file from the plot tool. "
    "Call plot now (line, scatter, or residuals) with a table path or xs/ys. "
    "Do not draw an ASCII chart or invent a trend. Allow still applies."
)

_DOCUMENT_FORCE_NOTICE = (
    "Exactness: this question asks for a file they can open. "
    "Call document now with format (pdf, docx, xlsx, csv, md, or txt), "
    "a title, and the full body. Do not paste the document into chat. "
    "Do not call doc_extract. Allow still applies."
)

_EVIDENCE_FORCE_NOTICE = (
    "Exactness: you are about to assert a contingent fact without a warrant "
    "from this turn's tools. Call the required tool now "
    "(weather, web_search+scrape, recall, inbox, inbound_sms, "
    "doc_extract, agenda, git_info, tasks, goals, analyze, vision, "
    "cas, units, plot, catalog, or document), "
    "or say you do not know. "
    "Do not guess."
)


_CATALOG_FORCE_NOTICE = (
    "Exactness: this question named a science catalog. "
    "Call catalog now (arxiv, horizons, apod, or ads). "
    "Do not invent a bibcode, an abstract, or an ephemeris. "
    "Do not scrape NASA or arXiv JavaScript."
)


def math_force_notice() -> str:
    return _CALC_FORCE_NOTICE


def cas_force_notice() -> str:
    return _CAS_FORCE_NOTICE


def units_force_notice() -> str:
    return _UNITS_FORCE_NOTICE


def plot_force_notice() -> str:
    return _PLOT_FORCE_NOTICE


def document_force_notice() -> str:
    return _DOCUMENT_FORCE_NOTICE


def catalog_force_notice() -> str:
    return _CATALOG_FORCE_NOTICE


def evidence_force_notice() -> str:
    return _EVIDENCE_FORCE_NOTICE


def weather_force_notice() -> str:
    """One-shot nudge when a weather ask never called the weather tool."""
    return (
        "This turn asks about the weather/forecast/temperature. "
        "Call the weather tool now. For another city pass place (a name, not "
        "coordinates). days includes today: tomorrow needs 2 or more (default 3). "
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
    cas_failed: bool = False,
    cas_detail: str = "",
    units_failed: bool = False,
    units_detail: str = "",
    plot_failed: bool = False,
    plot_detail: str = "",
    catalog_failed: bool = False,
    catalog_detail: str = "",
    document_failed: bool = False,
    document_detail: str = "",
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
    if "symbolic" in kinds:
        if cas_failed:
            detail = (cas_detail or "").lower()
            if "closed form" in detail or "no closed" in detail:
                return (
                    "No closed form — the CAS could not find one, and I will "
                    "not invent it."
                )
            if "timeout" in detail:
                return (
                    "The CAS timed out on that expression. I will not guess a "
                    "closed form."
                )
            return (
                "The CAS couldn't evaluate that. I will not recite a symbolic "
                "result from memory."
            )
        return (
            "I don't know — this needs a CAS result and I don't have a "
            "closed form from this turn."
        )
    if "units" in kinds:
        if units_failed:
            detail = (units_detail or "").lower()
            if "not a unit" in detail or "cmb" in detail:
                return (
                    "That is not a unit conversion — a frame change needs a "
                    "boost with published numbers, and I will not fake it."
                )
            return (
                "The units tool couldn't convert or look that up. I will not "
                "recite CODATA or invent a conversion."
            )
        return (
            "I don't know — this needs a units or constants result this turn, "
            "and I will not recite one from memory."
        )
    if "plot" in kinds:
        if plot_failed:
            return (
                "The plot tool couldn't draw that. I will not fake a chart "
                "in text."
            )
        return (
            "I don't know — this needs a plot file from this turn, and I "
            "will not draw one in ASCII."
        )
    if "document" in kinds:
        if document_failed:
            return (
                "I couldn't write that file. I will not paste a fake document "
                "into chat."
            )
        return (
            "I don't know — this needs a real file from this turn, and I "
            "will not pretend the chat is the document."
        )
    if "catalog" in kinds:
        if catalog_failed:
            return (
                "The catalog tool couldn't fetch that. I will not invent "
                "a paper or an ephemeris."
            )
        return (
            "I don't know — this needs an arXiv, Horizons, APOD, or ADS "
            "result this turn, and I will not invent one."
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
