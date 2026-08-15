"""Single source of truth for high-confidence user intents.

Preflight, tool-schema subsetting, and exactness finish gates used to each
carry their own copy of "this is weather / SMS / email". A new phrase had to
be taught in several files or a send tool would get hidden. Specs here own
the matchers; callers decide whether to nudge, shrink schemas, or refuse.

Draft reconstruction (complete_sms_draft, etc.) stays in those modules —
this catalog does not send, confirm, or skip Allow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentHint:
    kind: str
    expected_tools: tuple[str, ...]
    nudge: str


@dataclass(frozen=True)
class IntentSpec:
    kind: str
    patterns: tuple[re.Pattern[str], ...]
    expected_tools: tuple[str, ...]
    nudge: str
    full_surface: bool = False
    schema_tools: frozenset[str] = frozenset()
    exactness: tuple[re.Pattern[str], ...] = ()
    # When True, detect_intents emits this spec with no extra guards.
    auto_hint: bool = False
    # Add schema_tools onto the research-mode allowlist when the text matches.
    research_extra: bool = False
    # Substrings that force the full tool registry (outbound / personal).
    surface_phrases: tuple[str, ...] = ()

    def matches(self, text: str) -> bool:
        raw = text or ""
        if not raw.strip() or not self.patterns:
            return False
        return any(p.search(raw) for p in self.patterns)

    def to_hint(self) -> IntentHint:
        return IntentHint(
            kind=self.kind,
            expected_tools=self.expected_tools,
            nudge=self.nudge,
        )


# --- matchers (moved verbatim from preflight / claims) ---

_WEATHER_PRE = re.compile(
    r"(?i)\b("
    r"weather|forecast|temperature|how\s+hot|how\s+cold|"
    r"is\s+it\s+(going\s+to\s+)?(rain|snow)|umbrella|"
    r"degrees?\s+(outside|today)|humid"
    r")\b"
)
_WEATHER_EXACT = (
    re.compile(
        r"(?:what(?:'s|\s+is)|how(?:'s|\s+is)|check|tell\s+me).{0,24}"
        r"(?:weather|temperature|forecast)\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:weather|forecast|temperature)\b.{0,40}"
        r"(?:today|tonight|tomorrow|outside|now|near\s+me|\bin\s+\w+)",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:is\s+it|will\s+it)\s+(?:rain(?:ing)?|snow(?:ing)?|cold|hot|warm)\b",
        re.I,
    ),
)

_RECALL_PRE = re.compile(
    r"(?i)\b("
    r"what\s+did\s+i\s+(?:say|tell|ask)|"
    r"do\s+you\s+remember|"
    r"you\s+told\s+me|"
    r"from\s+(?:our|my)\s+(?:chat|conversation)"
    r")\b"
)

_INBOUND_SMS_PRE = re.compile(
    r"(?i)\b("
    r"did\s+\w+\s+text|"
    r"has\s+\w+\s+texted|"
    r"what\s+did\s+(?:they|\w+)\s+reply|"
    r"what\s+did\s+(?:they|\w+)\s+text|"
    r"text(?:ed)?\s+(?:me\s+)?back|"
    r"any\s+(?:texts?|sms|replies)\s+from|"
    r"did\s+(?:anyone|somebody)\s+text"
    r")\b"
)
_INBOUND_SMS_EXACT = (
    re.compile(r"\bdid\s+\w+\s+text(?:\s+me)?\b", re.I),
    re.compile(r"\b(?:any|new)\s+(?:texts?|sms)\s+from\b", re.I),
    re.compile(
        r"\bwhat\s+did\s+(?:\w+|they|he|she)\s+"
        r"(?:text|reply|say\s+back)\b",
        re.I,
    ),
    re.compile(r"\b(?:text(?:ed)?|sms)\s+(?:me\s+)?back\b", re.I),
    re.compile(
        r"\b(?:did\s+(?:anyone|somebody)|anyone)\s+text(?:\s+me)?\b",
        re.I,
    ),
)

_INBOX_PRE = re.compile(
    r"(?i)\b("
    r"(?:any|new)\s+(?:emails?|e-?mails?|mail|messages?)|"
    r"check\s+(?:my\s+)?(?:inbox|email|e-?mail|mail)|"
    r"what(?:'s|\s+is)\s+in\s+(?:my\s+)?(?:inbox|mail)|"
    r"unread\s+(?:mail|email|e-?mail)|"
    r"(?:did\s+i|have\s+i)\s+(?:get|got|received)\s+(?:any\s+)?(?:mail|email)|"
    r"emails?\s+today"
    r")\b"
)
_INBOX_EXACT = (
    re.compile(
        r"(?:what(?:'s|\s+is)|anything|any(?:thing)?\s+new).{0,24}"
        r"(?:in\s+)?(?:my\s+)?(?:inbox|email|mail)\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:check|look\s+(?:at|in)|open|read)\s+(?:my\s+)?"
        r"(?:inbox|email|mail)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:did\s+i\s+get|have\s+i\s+(?:got|gotten)|any)\s+"
        r"(?:an?\s+)?(?:email|mail|message)\s+from\b",
        re.I,
    ),
    re.compile(r"\b(?:emails?|mail)\s+from\b", re.I),
)

_DEEP_DIVE = re.compile(
    r"(?i)\b("
    r"investigate|"
    r"deep\s*-?\s*dive|"
    r"write\s+a\s+report|"
    r"research\s+report|"
    r"multi\s*-?\s*source|"
    r"thorough\s+research|"
    r"in\s*-?\s*depth\s+(?:research|look|analysis|report)|"
    r"cite\s+sources|"
    r"survey\s+the\b"
    r")\b"
)
_DEEP_DIVE_EXACT = (
    re.compile(r"\b(?:investigate|deep\s*-?\s*dive)\b", re.I),
    re.compile(r"\b(?:write\s+a\s+report|research\s+report)\b", re.I),
    re.compile(r"\b(?:multi\s*-?\s*source|thorough\s+research)\b", re.I),
    re.compile(r"\bin\s*-?\s*depth\s+(?:research|look|analysis|report)\b", re.I),
    re.compile(r"\b(?:cite\s+sources|survey\s+the)\b", re.I),
)

_DEADLINE_PACK = re.compile(
    r"(?i)\b("
    r"deadlines?|"
    r"what(?:'s|\s+is)\s+due|"
    r"what(?:'s|\s+is)\s+coming\s+up|"
    r"pack\s+my\s+week|"
    r"upcoming\s+deadlines?|"
    r"what(?:'s|\s+is)\s+on\s+(?:my\s+)?plate|"
    r"due\s+this\s+(?:week|month)|"
    r"what\s+do\s+i\s+owe"
    r")\b"
)

_ATTENTION = re.compile(
    r"(?i)\b("
    r"what\s+needs\s+(?:my\s+)?attention|"
    r"what(?:'s|\s+is)\s+(?:urgent|due\s+soon)|"
    r"anything\s+(?:urgent|overdue)|"
    r"what\s+should\s+i\s+(?:focus\s+on|prioritize)"
    r")\b"
)

_GOALS = re.compile(
    r"(?i)\b("
    r"(?:what(?:'s|\s+are)|show(?:\s+me)?|list)\s+"
    r"(?:my\s+)?(?:goals?|commitments?)|"
    r"(?:am\s+i\s+committed\s+to|what\s+am\s+i\s+(?:working\s+toward|"
    r"committed\s+to))|"
    r"(?:add|set|create)\s+(?:a\s+)?(?:goal|commitment)|"
    r"commit\s+to|"
    r"(?:delete|remove|drop|pause|resume|complete|finish)\s+"
    r"(?:that\s+|the\s+|this\s+|my\s+|both\s+(?:of\s+)?(?:those\s+|the\s+)?)?"
    r"(?:goals?|commitments?)|"
    r"(?:mark|set)\s+(?:that\s+|the\s+|my\s+)?(?:goal|commitment)\s+"
    r"(?:as\s+)?(?:done|complete|completed)|"
    r"mark\s+(?:it|that)\s+(?:as\s+)?(?:done|complete|completed)"
    r")\b"
)

_AGENDA_MENTION = re.compile(
    r"(?i)\b(calendar|agenda|meeting|appoint(?:ment)?|schedule an event)\b"
)
_BRIEFING_MENTION = re.compile(
    r"(?i)\b(briefing|morning summary|what'?s going on today)\b"
)
_TASK_MENTION = re.compile(
    r"(?i)\b("
    r"todo|to-?do|task list|checklist|"
    r"(?:list|show|add|create|mark|delete|remove)\s+"
    r"(?:a\s+|my\s+|the\s+|that\s+)?tasks?"
    r")\b"
)
_DOC_MENTION = re.compile(r"(?i)\b(\.pdf\b|pdf|document extract)\b")
# A document ask rarely says "pdf". "analyze the document I gave you" and "what
# does this document say" both used to match nothing, so the ask arrived with no
# expected tool at all. The noun has to be asked *about* — a bare "document" also
# appears in "document this decision", which is not a read. The \b keeps
# "documentation" out, since a word character follows there.
DOC_ASK = re.compile(
    r"(?i)\b(?:analys?[ez]e?|analyz|summari[sz]e|read|extract|"
    r"what(?:'s|\s+is)\s+in|what\s+does|go\s+through)\s+"
    r"(?:(?:this|the|that|my|those|these)\s+)?(?:documents?|pdfs?)\b"
)
_INBOX_MENTION = re.compile(r"(?i)\b(inbox|email|e-?mail|gmail|mail)\b")

WEATHER = IntentSpec(
    kind="weather",
    patterns=(_WEATHER_PRE,),
    expected_tools=("weather",),
    nudge=(
        "Intent preflight: this message asks about weather. "
        "Call the weather tool now. Do not scrape forecast websites "
        "and do not ask permission in chat."
    ),
    schema_tools=frozenset({"weather", "user_location", "web_fetch"}),
    exactness=_WEATHER_EXACT,
    auto_hint=True,
)

RECALL = IntentSpec(
    kind="recall",
    patterns=(_RECALL_PRE,),
    expected_tools=("recall",),
    nudge=(
        "Intent preflight: this message asks about something from "
        "prior chat or memory. Call the recall tool now before "
        "claiming you do not know or inventing what was said. "
        "Do not ask permission in chat."
    ),
    schema_tools=frozenset({"recall", "memory"}),
    exactness=(_RECALL_PRE,),
    auto_hint=True,
)

INBOUND_SMS = IntentSpec(
    kind="inbound_sms",
    patterns=(_INBOUND_SMS_PRE,),
    expected_tools=("inbound_sms",),
    nudge=(
        "Intent preflight: this message asks about inbound texts "
        "or a reply. Call inbound_sms now. Do not invent a reply "
        "body, do not web_search for private messages, and do not "
        "ask permission in chat."
    ),
    full_surface=True,
    schema_tools=frozenset({"inbound_sms", "send_sms", "contacts"}),
    exactness=_INBOUND_SMS_EXACT,
    auto_hint=True,
)

SMS_SEND = IntentSpec(
    kind="sms_send",
    patterns=(),
    expected_tools=("send_sms",),
    nudge="",
    full_surface=True,
    schema_tools=frozenset({"send_sms", "inbound_sms", "contacts"}),
    surface_phrases=(
        "text ",
        "sms",
        "send a text",
    ),
)

COMPOSE_EMAIL = IntentSpec(
    kind="compose_email",
    patterns=(),
    expected_tools=("send_email",),
    nudge="",
    full_surface=True,
    schema_tools=frozenset({"inbox", "send_email"}),
    surface_phrases=(
        "send an email",
        "email ",
    ),
)

INBOX = IntentSpec(
    kind="inbox",
    patterns=(_INBOX_PRE,),
    expected_tools=("inbox",),
    nudge=(
        "Intent preflight: this message asks about inbox/mail "
        "arrival. Call inbox (list or summarize). Do not call "
        "send_email unless they clearly asked to compose or send. "
        "Do not ask permission in chat."
    ),
    schema_tools=frozenset({"inbox", "send_email"}),
    exactness=_INBOX_EXACT,
    research_extra=True,
)

RESEARCH = IntentSpec(
    kind="research",
    patterns=(_DEEP_DIVE,),
    expected_tools=("research_report",),
    nudge=(
        "Intent preflight: this message asks for a deep dive or "
        "multi-source report. Call research_report now with the "
        "user's question as query (add recency=day or week for "
        "news). Do not invent citations, and do not ask permission "
        "in chat."
    ),
    schema_tools=frozenset(
        {"research_report", "web_search", "scrape", "web_fetch", "calculator"}
    ),
    exactness=_DEEP_DIVE_EXACT,
    auto_hint=True,
)

DEADLINE = IntentSpec(
    kind="deadline_pack",
    patterns=(_DEADLINE_PACK,),
    expected_tools=("tasks", "agenda"),
    nudge=(
        "Intent preflight: this message asks about deadlines or "
        "what is due. Call tasks(action=list) for open items, then "
        "agenda(action=list or range) for upcoming events, then "
        "summarize conflicts and stale tasks. Mutates still need "
        "Allow — do not ask permission in chat."
    ),
    schema_tools=frozenset({"tasks", "agenda"}),
    auto_hint=True,
    research_extra=True,
)

# "What needs my attention" is still a fair question; the tool that answered it
# is gone. It only ever aggregated tasks, goals and the near calendar, so the ask
# now goes to those directly. Expecting tasks alone keeps the round count honest —
# the nudge invites the calendar when the ask is really about the day.
ATTENTION = IntentSpec(
    kind="attention",
    patterns=(_ATTENTION,),
    expected_tools=("tasks",),
    nudge=(
        "Intent preflight: this message asks what is urgent or needs attention. "
        "Read it from the stores: call tasks for what is open and overdue, goals "
        "for active commitments, and agenda if the urgency is about today or "
        "tomorrow. Do not invent urgency. Do not ask permission in chat."
    ),
    schema_tools=frozenset({"tasks", "goals", "agenda"}),
    auto_hint=True,
)

GOALS = IntentSpec(
    kind="goals",
    patterns=(_GOALS,),
    expected_tools=("goals",),
    nudge=(
        "Intent preflight: this message asks about goals or "
        "commitments. Call goals now (list, add, pause/resume, "
        "done/complete, or drop with id). Completed goals leave the "
        "default active list — use status=done or status=all to see "
        "them again. Do not invent goals. Chores stay on tasks; "
        "identity prefs on memory. Allow still applies — do not ask "
        "permission in chat."
    ),
    schema_tools=frozenset({"goals"}),
    auto_hint=True,
)

AGENDA = IntentSpec(
    kind="agenda",
    patterns=(_AGENDA_MENTION,),
    expected_tools=("agenda",),
    nudge="",
    schema_tools=frozenset({"agenda"}),
    research_extra=True,
    surface_phrases=(
        "add to my calendar",
        "create an event",
        "calendar event",
        "create a calendar",
    ),
)

# "Morning summary" / "what's going on today" used to have one tool that stitched
# the day together. Without it the ask has to be assembled, so this widens the
# surface rather than naming a single call — and stays a schema hint, not an
# expected tool, because there is no longer one right answer to expect.
BRIEFING = IntentSpec(
    kind="briefing",
    patterns=(_BRIEFING_MENTION,),
    expected_tools=(),
    nudge="",
    schema_tools=frozenset({"agenda", "inbox", "tasks", "goals", "weather"}),
    research_extra=True,
)

TASKS = IntentSpec(
    kind="tasks",
    patterns=(_TASK_MENTION,),
    expected_tools=("tasks",),
    nudge=(
        "Intent preflight: this message asks about to-dos. Call tasks "
        "now (list, add, or remove). Do not invent tasks. Do not call "
        "weather or web_search. Allow still applies — do not ask "
        "permission in chat."
    ),
    schema_tools=frozenset({"tasks"}),
    auto_hint=True,
    research_extra=True,
)

DOCS = IntentSpec(
    kind="docs",
    patterns=(_DOC_MENTION, DOC_ASK),
    expected_tools=("doc_extract",),
    nudge="",
    schema_tools=frozenset({"doc_extract"}),
    research_extra=True,
)

CATALOG: tuple[IntentSpec, ...] = (
    WEATHER,
    RECALL,
    INBOUND_SMS,
    SMS_SEND,
    COMPOSE_EMAIL,
    INBOX,
    RESEARCH,
    DEADLINE,
    ATTENTION,
    GOALS,
    AGENDA,
    BRIEFING,
    TASKS,
    DOCS,
)

BY_KIND: dict[str, IntentSpec] = {s.kind: s for s in CATALOG}

AUTO_HINTS: tuple[IntentSpec, ...] = tuple(s for s in CATALOG if s.auto_hint)

FULL_SURFACE_KINDS = frozenset(
    s.kind for s in CATALOG if s.full_surface
) | frozenset({"sms"})  # legacy alias some callers still use

FULL_SURFACE_PHRASES: tuple[str, ...] = tuple(
    phrase for s in CATALOG for phrase in s.surface_phrases
)


def spec(kind: str) -> IntentSpec:
    found = BY_KIND.get(kind)
    if found is None:
        raise KeyError(kind)
    return found


def exactness_match(kind: str, text: str) -> bool:
    """True when the narrower exactness patterns for *kind* match."""
    item = BY_KIND.get(kind)
    if item is None or not item.exactness:
        return False
    raw = text or ""
    return any(p.search(raw) for p in item.exactness)


def research_extras_for_text(text: str) -> set[str]:
    """Tools to add onto the research allowlist for this text."""
    extra: set[str] = set()
    for item in CATALOG:
        if item.research_extra and item.matches(text):
            extra |= set(item.schema_tools)
    if _INBOX_MENTION.search(text or ""):
        extra.update({"inbox", "send_email"})
    return extra


def must_keep_full_surface_text(text: str) -> bool:
    """Phrase-level full-surface (does not inspect drafts).

    SMS ``text `` is a substring of OCR/PDF asks ("read the text in …").
    Those vetoes live on the sms skill card; they do not hide a real send.
    """
    lowered = (text or "").lower()
    from arelis.core.skills import sms_negative_hit

    if sms_negative_hit(lowered):
        skip = set(SMS_SEND.surface_phrases)
        return any(w in lowered for w in FULL_SURFACE_PHRASES if w not in skip)
    return any(w in lowered for w in FULL_SURFACE_PHRASES)
