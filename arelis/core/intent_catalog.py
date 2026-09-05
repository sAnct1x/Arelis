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


# "Who are you" is identity, not a web lookup. Do not steal "who is this"
# (a fighter on TV, a photo) or "who won".
_IDENTITY_ASK = re.compile(
    r"(?i)^\s*(?:"
    r"who\s+are\s+you|"
    r"what\s+are\s+you|"
    r"what(?:'s|\s+is)\s+your\s+name|"
    r"what(?:'s|\s+is)\s+your\s+name\s+again|"
    r"introduce\s+yourself"
    r")[?!.\s]*$"
)

# The clock is already in the system prompt (now_line). These asks must not
# take the unmatched "what/who/when" web fallback, which fail-opens every
# tool schema and costs a 30s prefill for the time of day.
_LOCAL_CLOCK = re.compile(
    r"(?i)^\s*(?:"
    r"what\s+time\s+is\s+it(?:\s+(?:now|right\s+now|currently))?"
    r"|what(?:'s|\s+is)\s+the\s+time(?:\s+(?:now|right\s+now))?"
    r"|what(?:'s|\s+is)\s+(?:the\s+)?current\s+time"
    r"|tell\s+me\s+the\s+time"
    r"|what\s+day\s+is\s+it(?:\s+today)?"
    r"|what(?:'s|\s+is)\s+today'?s\s+date"
    r"|what\s+date\s+is\s+it"
    r"|what(?:'s|\s+is)\s+the\s+date(?:\s+today)?"
    r"|what\s+day\s+of\s+the\s+week(?:\s+is\s+it)?"
    r")[?!.\s]*$"
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
    # Scheduled jobs are imperatives: "Get the forecast for Springfield, IL".
    # The patterns above only heard questions ("what's the weather today")
    # and "in <place>", so a 9am weather email never forced the weather tool
    # and then refused with a web-page warrant.
    re.compile(
        r"\b(?:get|fetch|look\s+up|pull|give\s+me)\b.{0,60}"
        r"\b(?:weather|forecast|temperature)s?\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:weather|forecast)\b.{0,48}\bfor\s+\w+",
        re.I | re.S,
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
    r"(?:any|new)\s+(?:emails?|e-?mails?|emiles?|emil|mail|messages?)|"
    r"(?:any\s+)?new\s+(?:emails?|emiles?|emil)|"
    r"check\s+(?:my\s+|your\s+|the\s+)?(?:inbox|in\s+box|email|e-?mail|emiles?|emil|mail)|"
    r"what(?:'s|\s+is)\s+in\s+(?:my\s+|your\s+)?(?:inbox|in\s+box|mail)|"
    r"unread\s+(?:mail|email|e-?mail)|"
    r"(?:did\s+(?:i|you)|have\s+(?:i|you))\s+(?:get|got|received|check)(?:\s+any)?\s+(?:new\s+)?(?:mail|email|emiles?|emil)|"
    r"(?:emails?|emiles?)\s+today|"
    r"(?:delete|trash|archive|remove)\s+(?:the\s+|that\s+|this\s+)?(?:e-?mail|mail|message)|"
    r"in\s+box"
    r")\b"
)
_INBOX_EXACT = (
    re.compile(
        r"(?:what(?:'s|\s+is)|anything|any(?:thing)?\s+new).{0,24}"
        r"(?:in\s+)?(?:my\s+|your\s+)?(?:inbox|in\s+box|email|emiles?|emil|mail)\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:check|look\s+(?:at|in)|open|read)\s+(?:my\s+|your\s+|the\s+)?"
        r"(?:inbox|in\s+box|email|mail|emiles?|emil)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:did\s+i\s+get|have\s+i\s+(?:got|gotten)|any)\s+"
        r"(?:an?\s+)?(?:email|mail|emile|emil|message)\s+from\b",
        re.I,
    ),
    re.compile(r"\b(?:emails?|mail|emiles?)\s+from\b", re.I),
    re.compile(
        r"\b(?:delete|trash|archive|remove)\s+(?:the\s+|that\s+|this\s+)?"
        r"(?:e-?mail|mail|message)\b",
        re.I,
    ),
    re.compile(r"\bin\s+box\b", re.I),
    re.compile(
        r"(?i)\b(?:do\s+i\s+have|any|have\s+i\s+got)\s+"
        r"(?:any\s+)?unread\s+(?:mail|email|e-?mail|messages?)\b"
    ),
)

_DEEP_DIVE = re.compile(
    r"(?i)\b("
    r"investigate|"
    r"deep\s*-?\s*dive|"
    r"deeply\s+research|"
    r"deep\s+research|"
    r"write\s+a\s+report|"
    r"research\s+report|"
    r"research\s+prompt|"
    r"evidence[- ]based|"
    r"hype\s+vs\.?\s+reality|"
    r"comparative\s+table|"
    r"multi\s*-?\s*source|"
    r"thorough\s+research|"
    r"in\s*-?\s*depth\s+(?:research|look|analysis|report)|"
    r"cite\s+sources|"
    r"survey\s+the\b"
    r")\b"
)
_DEEP_DIVE_EXACT = (
    re.compile(r"\b(?:investigate|deep\s*-?\s*dive)\b", re.I),
    re.compile(r"\b(?:deeply\s+research|deep\s+research)\b", re.I),
    re.compile(r"\b(?:write\s+a\s+report|research\s+report|research\s+prompt)\b", re.I),
    re.compile(r"\b(?:evidence[- ]based|hype\s+vs\.?\s+reality|comparative\s+table)\b", re.I),
    re.compile(r"\b(?:multi\s*-?\s*source|thorough\s+research)\b", re.I),
    re.compile(r"\bin\s*-?\s*depth\s+(?:research|look|analysis|report)\b", re.I),
    re.compile(r"\b(?:cite\s+sources|survey\s+the)\b", re.I),
)

# Battery / device specs say "temperature" without asking for a forecast.
_WEATHER_SPEC_VETO = re.compile(
    r"(?i)\b("
    r"operating\s+temperature|"
    r"temperature\s+(?:range|window|limit|limits|stability|coefficient)|"
    r"room[- ]temperature|"
    r"(?:high|low|elevated|ambient)[- ]temperature|"
    r"cell\s+temperature|"
    r"junction\s+temperature|"
    r"melting\s+temperature|"
    r"at\s+temperature|"
    r"thermal\s+noise|"
    r"kelvin"
    r")\b|"
    r"\b\d+(?:\.\d+)?\s*K\b"
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
_DOC_MENTION = re.compile(r"(?i)\b(document extract)\b")
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
_INBOX_MENTION = re.compile(
    r"(?i)\b(inbox|in\s+box|email|e-?mail|gmail|mail|emiles?|emil)\b"
)

# "There is a table in this ask." Preflight nudges toward the analyze tool on it,
# plan_nudge builds a plan from it, and the exactness gate refuses invented row
# counts because of it — three questions about one fact, so the fact lives here.
#
# All three carried their own copy. The two in preflight and plan_nudge were
# byte-identical; claims' differed by re.S, which is the only reason a
# "summarize\nthis table" spanning a newline was a table to one gate and not to
# the others. DOTALL is kept: it is the reading that treats a wrapped sentence
# the same as a flat one.
_TABULAR = (
    # A path-like token with a table extension.
    re.compile(r"[^\s\"']+\.(?:csv|xlsx|xls|tsv|tab|json)\b", re.I),
    # The format named outright.
    re.compile(r"\b(?:csv|xlsx|xls|tsv|spreadsheet|dataframe|excel)\b", re.I),
    # An action on tabular data without naming a format.
    re.compile(
        r"\b(?:summarize|analyze|describe)\b.{0,48}\b(?:data|table|sheet)\b",
        re.I | re.S,
    ),
)


def mentions_tabular_data(text: str) -> bool:
    """True when the ask names a table, a spreadsheet, or a file that holds one."""
    raw = text or ""
    if not raw.strip():
        return False
    return any(p.search(raw) for p in _TABULAR)


# "The file is at C:\\...\\books.xlsx" names a spreadsheet but is not a request to
# read one — it is the user fixing a path Arelis got wrong. Answering it by
# analysing the file is how a correction turns into an unasked-for tool call.
#
# This lived, verbatim, in all three modules that ask about tables. It travels
# with the matcher because it is not a separate fact: it is the exception to that
# one, and a copy that fell behind would let the correction be read as an ask.
_PATH_CORRECTION = re.compile(
    r"(?i)\b("
    r"(?:file|path|document)\s+(?:is\s+)?(?:located\s+)?at|"
    r"here(?:'s|\s+is)\s+the\s+(?:file|path)|"
    r"use\s+this\s+(?:file|path)|"
    r"correct\s+path"
    r")\b"
)


def corrects_a_path(text: str) -> bool:
    """True when the ask is fixing a file location rather than asking about it."""
    raw = text or ""
    return bool(raw.strip()) and bool(_PATH_CORRECTION.search(raw))


# --- driving the user's own Chrome ---
#
# Preflight and plan_nudge both read these, and both used to own a copy. The
# copies drifted, always in the same direction: preflight learned a phrase and
# plan_nudge did not. "Walk to the museum" was directions to the nudge and
# nothing to the plan; so were "book us a table", "table for 4", "describe the
# page" and "tell me what's on this tab".
#
# The result was worse than either alone. Both are system messages on the same
# turn, so the model was told to call browser(action=maps) and, in the next
# breath, handed a plan for a different tool — or no plan at all where every
# other intent has one. Two matchers that disagree do not degrade gracefully;
# they argue in the prompt.
BROWSER_MAPS = re.compile(
    r"(?i)\b("
    r"directions\s+to|"
    r"how\s+do\s+i\s+get\s+to|"
    r"(?:google\s+)?maps\s+to|"
    r"drive\s+to|"
    r"walk\s+to|"
    r"route\s+to|"
    r"(?:text|sms|send)\s+(?:me\s+)?(?:the\s+)?directions"
    r")\b"
)

BROWSER_MAPS_SEND = re.compile(
    r"(?i)\b(?:text|sms|send)\s+(?:me\s+)?(?:the\s+)?directions\b"
)

BROWSER_SEARCH = re.compile(
    r"(?i)\b("
    r"search\s+(?:on\s+|for\s+)?(?:youtube|yt)|"
    r"(?:youtube|yt)\s+search|"
    r"search\s+youtube|"
    r"look\s+(?:up|for)\s+.{0,48}\s+on\s+youtube|"
    r"find\s+.{0,48}\s+on\s+youtube|"
    r"search\s+google\s+for|"
    r"google\s+this\s+in\s+(?:the\s+)?(?:browser|chrome)|"
    r"search\s+for\s+.{0,80}\bvideos?\b|"
    r"search\s+(?:on\s+)?amazon|"
    r"look\s+(?:up|for)\s+.{0,48}\s+on\s+amazon"
    r")\b"
)

BROWSER_FIRST = re.compile(
    r"(?i)\b("
    r"(?:play|open|click|watch)\s+(?:the\s+)?"
    r"(?P<n>first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|[1-5])"
    r"(?:\s+(?:one|result|video|link|hit))?"
    r"|the\s+(?P<n2>first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|[1-5])"
    r"\s+(?:one|result|video|link|hit)"
    r")\b"
)

BROWSER_CART = re.compile(
    r"(?i)\b("
    r"add\s+(?:it\s+|that\s+|this\s+|them\s+)?to\s+(?:(?:the|my)\s+)?(?:cart|bag)|"
    r"put\s+(?:it\s+|that\s+|this\s+)?in\s+(?:(?:the|my)\s+)?(?:cart|bag)"
    r")\b"
)

# Table / venue reservation in her Chrome (not the agenda calendar).
BROWSER_RESERVE = re.compile(
    r"(?i)\b("
    r"reserve\s+a\s+table|"
    r"book\s+a\s+table|"
    r"book\s+us\s+a\s+table|"
    r"get\s+(?:us\s+)?a\s+table|"
    r"make\s+(?:a\s+|us\s+a\s+)?reservation|"
    r"reservation\s+(?:at|for)|"
    r"table\s+for\s+\d|"
    r"opentable|"
    r"\bresy\b"
    r")\b"
)

# Compact text of the tab she is already on (not scrape-the-web).
BROWSER_READ = re.compile(
    r"(?i)\b("
    r"read\s+(?:this|the|my)\s+(?:tab|page)|"
    r"what(?:'s|\s+is|s)\s+on\s+(?:this|the|my)\s+(?:tab|page)|"
    r"what\s+does\s+(?:this|the)\s+(?:tab|page)\s+say|"
    r"tell\s+me\s+what(?:'s|\s+is)\s+on\s+(?:this|the)\s+(?:tab|page)|"
    r"describe\s+(?:what(?:'s|\s+is)\s+on\s+)?(?:the\s+|this\s+)?(?:page|tab)"
    r")\b"
)

# Click Sign in / Log in on the tab she is already on — not a fake action, not a
# guessed accounts.google.com URL. These three were byte-identical in both files.
LOGIN_NOUN = r"(?:sign[\s-]?in|log[\s-]?in|login)"
BROWSER_CLICK_SIGNIN = re.compile(
    r"(?i)\b("
    r"(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?" + LOGIN_NOUN + r"|"
    r"(?:go|navigate|take\s+me|bring\s+me)\s+to\s+(?:the\s+)?" + LOGIN_NOUN + r"|"
    r"open\s+(?:the\s+)?" + LOGIN_NOUN + r"|"
    r"proceed\s+with\s+(?:sign(?:ing)?|log(?:ging)?)[\s-]?in|"
    r"sign\s+me\s+in|"
    r"log\s+me\s+in"
    r")\b"
)
HOWTO_SIGNIN = re.compile(r"(?i)\bhow\s+(?:do\s+i|to)\s+(?:sign|log)\s*in\b")
BARE_SIGNIN = re.compile(r"(?i)^\s*(?:please\s+)?(?:sign|log)\s*in\s*[.!?]*$")

WEATHER = IntentSpec(
    kind="weather",
    patterns=(_WEATHER_PRE,),
    expected_tools=("weather",),
    nudge=(
        "Intent preflight: this message asks about weather. "
        "Call the weather tool now. For another city pass place "
        "(a name, not coordinates). days includes today; tomorrow "
        "needs 2 or more. Do not scrape forecast websites "
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
        {
            "research_report",
            "web_search",
            "scrape",
            "web_fetch",
            "calculator",
            "python",
            "cas",
            "units",
        }
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

_DOCUMENT_CREATE = (
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
    re.compile(
        r"(?i)\b(?:create|make|write|generate)\s+"
        r"(?:(?:me\s+)?(?:a\s+|an\s+)?)?"
        r"(?:\d+\s*[-\s]?\s*page\s+)?(?:pdf\s+)?report\b"
        r".{0,40}\b(?:pdf|docx|word)\b"
    ),
)

DOCUMENT = IntentSpec(
    kind="document",
    patterns=_DOCUMENT_CREATE,
    expected_tools=("document",),
    nudge=(
        "Intent preflight: this message asks for a file they can open. "
        "Call document now with format (pdf, docx, xlsx, csv, md, or txt), "
        "a title, and the full body. Do not dump the document into chat. "
        "Do not call doc_extract — that reads an existing PDF. "
        "Allow still applies — do not ask permission in chat."
    ),
    schema_tools=frozenset({"document"}),
    auto_hint=True,
    research_extra=True,
)

_PLOT_MENTION = (
    re.compile(r"(?i)\bplot\s+(?:this|the|my|it)\b"),
    re.compile(r"(?i)\b(?:scatter|line)\s+plot\b"),
    re.compile(r"(?i)\bplot\s+residuals\b"),
    re.compile(r"(?i)\bfit\s+a\s+line\b"),
    re.compile(r"(?i)\b(?:line|bar|scatter)\s+chart\b"),
    re.compile(r"(?i)\bchart\s+(?:this|the|my)\b"),
    re.compile(r"(?i)\bmake\s+a\s+(?:plot|chart|graph)\b"),
    # claims.py had this one and the catalog did not, so "show me a chart of
    # this" was a chart to the gate that refuses invented numbers and not a
    # chart to the nudge that would have sent the plot tool at it.
    re.compile(r"(?i)\bshow\s+me\s+a\s+(?:plot|chart|graph)\b"),
    # "gives me a graph of position over time" never said "make a plot".
    re.compile(r"(?i)\b(?:give|gives|draw|write)\s+(?:me\s+)?(?:a\s+)?(?:graph|plot|chart)\b"),
    re.compile(r"(?i)\b(?:a\s+)?graph\s+of\b"),
    re.compile(r"(?i)\b(?:position|height|trajectory)\s+over\s+time\b"),
    re.compile(r"(?i)\bplot\s+.{0,40}\b(?:csv|tsv|xlsx|spreadsheet|columns?)\b"),
    re.compile(r"(?i)\bplot\s+[a-zA-Z]\s*="),
)

PLOT = IntentSpec(
    kind="plot",
    patterns=_PLOT_MENTION,
    expected_tools=("plot",),
    nudge=(
        "Intent preflight: this message asks for a chart. Call plot now "
        "(line, scatter, or residuals) with xs/ys numbers and out='name.png', "
        "or a CSV via path= plus x/y columns. path= is the table, not the PNG. "
        "If you need numbers first, call python, then plot. Allow applies. "
        "Do not draw an ASCII chart. Do not call image."
    ),
    schema_tools=frozenset({"plot", "analyze"}),
    auto_hint=True,
    research_extra=True,
)

_CATALOG_MENTION = (
    re.compile(r"(?i)\barxiv\b"),
    re.compile(r"(?i)\bpreprints?\b"),
    re.compile(r"(?i)\bjpl\s+horizons\b"),
    re.compile(r"(?i)\bephemeris\b"),
    re.compile(r"(?i)\bask\s+horizons\b"),
    re.compile(
        r"(?i)\bwhere is (?:mercury|venus|mars|jupiter|saturn|uranus|"
        r"neptune|pluto|the moon)\b.{0,24}\b(tonight|today|now)\b"
    ),
    re.compile(r"(?i)\b(apod|astronomy picture of the day)\b"),
    re.compile(r"(?i)\bnasa'?s? (?:photo|picture) of the day\b"),
    re.compile(r"(?i)\b(nasa\s+ads|adsabs|astrophysics data system)\b"),
    # Asking for a paper without naming the catalog. These four were only in
    # claims.py, so "find me a paper on X" was refused for having no warrant
    # while nothing had told the model to go and get one.
    re.compile(r"(?i)\bfind me a paper\b"),
    re.compile(r"(?i)\blook up a paper\b"),
    re.compile(r"(?i)\bpapers on\b"),
    re.compile(r"(?i)\bsearch arxiv\b"),
)

_SOLAR_BODY_NAMES = (
    r"mercury|venus|earth|mars|jupiter|saturn|uranus|neptune|pluto|"
    r"the\s+moon|moon|the\s+sun|sun|ceres|vesta|pallas|hygiea|"
    r"phobos|deimos|io|europa|ganymede|callisto|titan|enceladus|"
    r"mimas|tethys|dione|rhea|iapetus|triton"
)

_SOLAR_BODY_ASK = (
    re.compile(rf"(?i)\bhow big is (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\b(?:radius|diameter)\s+of (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\b(?:{_SOLAR_BODY_NAMES})\b.{{0,28}}\b(?:radius|diameter)\b"),
    re.compile(rf"(?i)\b(?:gravity|surface gravity)\s+on (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\b(?:{_SOLAR_BODY_NAMES})\b.{{0,20}}\bgravity\b"),
    re.compile(rf"(?i)\bhow massive is (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\bmass of (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\bwhere is (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\bhow far (?:away )?is (?:{_SOLAR_BODY_NAMES})\b"),
    re.compile(rf"(?i)\b(?:{_SOLAR_BODY_NAMES})\b.{{0,20}}\b(?:how far|how big)\b"),
)

SOLAR_BODY = IntentSpec(
    kind="solar",
    patterns=_SOLAR_BODY_ASK,
    expected_tools=("solar", "catalog", "units"),
    nudge=(
        "Intent preflight: a planet/moon fact. Reality's solar lab can "
        "answer it (solar action=body) from the live IAS15 state and the "
        "IAU/DE440 numbers the sim uses. catalog Horizons and units "
        "constants are also fine. Do not recite GM or radius from memory."
    ),
    schema_tools=frozenset({"solar", "catalog"}),
    auto_hint=True,
    research_extra=True,
)

_SOLAR_STATUS_ASK = (
    re.compile(r"(?i)\bsolar system status\b"),
    re.compile(r"(?i)\bdump the solar(?: system)?(?: state| status)?\b"),
    re.compile(r"(?i)\bsolar system state\b"),
)
_EARTH_STATUS_ASK = (
    re.compile(r"(?i)\bearth status\b"),
    re.compile(r"(?i)\bdump the earth(?: state| status)?\b"),
    re.compile(r"(?i)\bearth state\b"),
)

SOLAR_STATUS = IntentSpec(
    kind="solar_status",
    patterns=_SOLAR_STATUS_ASK,
    expected_tools=("solar",),
    nudge=(
        "Intent preflight: they asked for the solar lab HUD or a dump. "
        "Call solar with action=status (or dump if they said dump). "
        "Do not open the browser. Do not reuse a prior maps/drive turn."
    ),
    schema_tools=frozenset({"solar"}),
    auto_hint=True,
)

EARTH_STATUS = IntentSpec(
    kind="earth_status",
    patterns=_EARTH_STATUS_ASK,
    expected_tools=("earth",),
    nudge=(
        "Intent preflight: they asked for Earth-zone status or a dump. "
        "Call earth with action=status (or dump if they said dump). "
        "Do not call solar. Do not open the browser."
    ),
    schema_tools=frozenset({"earth"}),
    auto_hint=True,
)


def solar_status_action(text: str) -> str:
    return "dump" if re.search(r"(?i)\bdump\b", text or "") else "status"


def earth_status_action(text: str) -> str:
    return "dump" if re.search(r"(?i)\bdump\b", text or "") else "status"


def run_script_path(text: str) -> str:
    """Named .py in a run/execute ask, or empty."""
    match = _RUN_SCRIPT_FILE.search(text or "")
    return str(match.group("path") or "").strip() if match else ""

SCIENCE_CATALOG = IntentSpec(
    kind="catalog",
    patterns=_CATALOG_MENTION,
    expected_tools=("catalog",),
    nudge=(
        "Intent preflight: this message named a science catalog. Call catalog "
        "now (arxiv, horizons, apod, or ads). Do not invent a paper or "
        "ephemeris. Do not scrape NASA JavaScript."
    ),
    schema_tools=frozenset({"catalog"}),
    auto_hint=True,
    research_extra=True,
)

# Phrase-only. "run diagnostics on my car" and "don't run diagnostics" are not
# a request to execute this checkout's pytest tree.
_DIAGNOSTICS_ASK = re.compile(
    r"(?i)(?<!n't )(?<!not )(?<!never )\brun\s+diagnostics\b(?!\s+on\b)"
)

DIAGNOSTICS = IntentSpec(
    kind="diagnostics",
    patterns=(_DIAGNOSTICS_ASK,),
    expected_tools=("diagnostics",),
    nudge=(
        "Intent preflight: they asked to run diagnostics. "
        "Call diagnostics now. Do not invent pass/fail counts from memory. "
        "Allow still applies — do not ask permission in chat."
    ),
    schema_tools=frozenset({"diagnostics"}),
    auto_hint=True,
    research_extra=True,
)

# Phrase-only. "watch a movie" / "port wine" are not a house-watch ask.
_WATCH_ASK = re.compile(
    r"(?i)(?<!n't )(?<!not )"
    r"(?:\bare we (?:safe|protected|secure)\b|"
    r"\bhouse watch\b|"
    r"\bwatch status\b|"
    r"\bsecurity (?:watch|status|check)\b|"
    r"\b(?:open ports|ports open)\b|"
    r"\bmass api\b|"
    r"\b(?:api (?:budget|flood|quota)|being (?:hammered|scanned))\b|"
    r"\b(?:inbound lock|egress mute|auth(?:entication)? fail)\b)"
)

# Phrase-only. "run diagnostics" / "run the tests" / schedule "run now" stay out.
_RUN_SCRIPT_FILE = re.compile(
    r"(?i)(?<!n't )(?<!not )(?<!never )\b(?:run|execute)\s+"
    r"(?!diagnostics\b)(?!the\s+tests\b)(?!this\s+job\b)(?!the\s+job\b)(?!now\b)"
    r"(?:(?:the|that|my)\s+(?:script|program|file)\s+)?"
    r"(?P<path>[\w./\\-]+\.py)\b"
)
_RUN_SCRIPT_BARE = re.compile(
    r"(?i)(?<!n't )(?<!not )(?<!never )\b(?:run|execute)\s+"
    r"(?:the|that|my)\s+(?:script|program)\b"
    r"(?!\s+now\b)(?!\s+job\b)"
)
_RUN_IT_AGAIN = re.compile(
    r"(?i)(?<!n't )(?<!not )(?<!never )\brun\s+it\s+again\b"
)

RUN_SCRIPT = IntentSpec(
    kind="run_script",
    patterns=(_RUN_SCRIPT_FILE, _RUN_SCRIPT_BARE, _RUN_IT_AGAIN),
    expected_tools=("run_script",),
    nudge=(
        "Intent preflight: they asked to run a project program. "
        "Call run_script with the .py they named. Not a shell. "
        "Not diagnostics. Not schedule run_now. "
        "Allow still applies — do not ask permission in chat."
    ),
    schema_tools=frozenset({"run_script"}),
    auto_hint=True,
)

WATCH = IntentSpec(
    kind="watch",
    patterns=(_WATCH_ASK,),
    expected_tools=("watch",),
    nudge=(
        "Intent preflight: they asked about the house watch (ports, inbound, "
        "outbound APIs). Call watch now. Report the snapshot. Do not invent a "
        "threat or claim the PC is fully secured."
    ),
    schema_tools=frozenset({"watch"}),
    auto_hint=True,
    research_extra=True,
)

# Spoken inspect: how she works / where a feature lives / read her source.
# Not generic "how does X work" (pytest, physics, interference, sign-in).
# Write verbs (fix/edit/patch/change) are excluded — those are inspect_write.
# "your source" / "confirm gate" alone are not an ask — need a read/how verb.
_SOURCE_WRITE = re.compile(
    r"(?i)\b(?:fix|edit|patch|change)\b.{0,48}(?:"
    r"confirm(?:\s+gate|\s+writes?)?|"
    r"policy\.py|"
    r"(?:her|your|the|own)\s+source|"
    r"your\s+own\s+source|"
    r"tool_subset(?:\.py)?|"
    r"orchestrator(?:\.py)?|"
    r"drive(?:\.py|\s+strip)"
    r")\b"
)

# Shared with path / file / source asks. "email me docs/…" has no read verb.
_INSPECT_READ_VERB = (
    r"(?:read|show(?:\s+me)?|look\s+(?:at|through)|inspect|"
    r"what(?:'s|\s+is)\s+in|what\s+does|"
    r"where(?:'s|\s+is)|tell\s+me(?:\s+what)?|how\s+does|how\s+do\s+you|open)"
)

_INSPECT_CONFIRM = re.compile(
    r"(?i)(?:"
    r"how\s+do\s+you\s+confirm(?:\s+writes?)?|"
    r"how\s+does\s+(?:my\s+|the\s+|your\s+)?confirm(?:\s+gate)?\s+work|"
    + _INSPECT_READ_VERB
    + r"\b.{0,40}\bconfirm\s+(?:writes?|gate)\b"
    r")"
)
_INSPECT_DRIVE = re.compile(r"(?i)\bdrive\s+strip\b")
# Filename alone is not an inspect ask ("email me policy.py"). Same verb as paths.
_INSPECT_BARE_FILE_ASK = re.compile(
    r"(?i)"
    + _INSPECT_READ_VERB
    + r"\b.{0,80}\b(?:"
    r"policy\.py|"
    r"tool_subset(?:\.py)?|"
    r"orchestrator\.py|"
    r"drive\.py"
    r")\b"
)
_HOW_YOU_WORK_PATH = "docs/architecture.md"
_INSPECT_HOW_YOU_WORK = re.compile(
    r"(?i)(?:"
    r"how\s+do\s+you\s+work|"
    r"how\s+you\s+work|"
    + _INSPECT_READ_VERB
    + r"\b.{0,40}\b(?:your|her)\s+(?:own\s+)?source\b"
    r")"
)
_INSPECT_EXPLICIT_PATH = re.compile(
    r"(?i)\b((?:arelis|docs)[/\\][A-Za-z0-9_./\\-]+)"
)
# Path mention alone is not an inspect ask ("email me docs/…"). Need a read verb.
_INSPECT_PATH_ASK = re.compile(
    r"(?i)"
    + _INSPECT_READ_VERB
    + r"\b.{0,80}\b(?:arelis|docs)[/\\]"
)
# "look at the files" / "how accurate is the space sim" — a crawl, not a named path.
_INSPECT_CODEBASE = re.compile(
    r"(?i)(?:"
    r"(?:look\s+(?:at|through)|read|show(?:\s+me)?|inspect|review|assess|dig\s+into)\s+"
    r"(?:the\s+)?(?:files?|code|source|workspace|folder|tree|checkout|sandbox)"
    r"|"
    r"investigate\b.{0,80}\b(?:files?|code|source|workspace|folder|checkout)"
    r"|"
    r"(?:accurate\s+assessment|how\s+accurate|glaring\s+holes|biggest\s+holes|"
    r"what(?:'s|\s+is)\s+missing)\b.{0,120}"
    r"(?:simulat|physics|code|source|files?)"
    r"|"
    r"(?:simulat|physics\s+code|n-?body).{0,80}"
    r"(?:how\s+accurate|holes?|missing|limitation)"
    r")"
)
_INSPECT_PHYSICS = re.compile(
    r"(?i)(?:"
    r"solar\s+system|"
    r"space\s+simulat|"
    r"(?:n-?body|orbital)\s|"
    r"physics\s+(?:engine|sim|code|room|files?)"
    r"|\breality\b.{0,40}\b(?:sim|engine|code|files?|accurac)"
    r"|\brebound\b"
    r"|\bias15\b"
    r")"
)
PHYSICS_INSPECT_PATH = "arelis/physics/engine.py"
PHYSICS_INSPECT_FANOUT = (
    "arelis/physics/engine.py",
    "arelis/physics/constants.py",
    "arelis/physics/horizons.py",
    "arelis/physics/scene.py",
)

_INSPECT_PATTERNS = (
    _INSPECT_CONFIRM,
    _INSPECT_DRIVE,
    _INSPECT_BARE_FILE_ASK,
    _INSPECT_HOW_YOU_WORK,
    _INSPECT_PATH_ASK,
    _INSPECT_CODEBASE,
)

_BARE_INSPECT_FILES = (
    ("policy.py", "arelis/tools/policy.py"),
    ("tool_subset.py", "arelis/core/tool_subset.py"),
    ("orchestrator.py", "arelis/core/orchestrator.py"),
    ("drive.py", "arelis/ui/panels/drive.py"),
)


def looks_like_source_write(text: str) -> bool:
    """True for fix/edit/patch her confirm gate / policy.py / source. Write + Allow."""
    raw = text or ""
    return bool(raw.strip()) and bool(_SOURCE_WRITE.search(raw))


def looks_like_source_inspect(text: str) -> bool:
    """True when they ask how she works, or to read her source. Not generic how-does-X."""
    if looks_like_source_write(text):
        return False
    raw = text or ""
    if not raw.strip():
        return False
    # A PDF under docs/ is a document, not her source. "what does docs/x.pdf
    # say" must stay doc_extract (W4), not a workspace read of the package.
    if re.search(r"(?i)\.(pdf|docx?|xlsx?|pptx?|csv|tsv)\b", raw):
        return False
    return any(p.search(raw) for p in _INSPECT_PATTERNS)


def inspect_read_path(text: str) -> str | None:
    """Canonical workspace path, or None."""
    raw = text or ""
    if not raw.strip():
        return None
    explicit = _INSPECT_EXPLICIT_PATH.search(raw)
    if explicit:
        return explicit.group(1).replace("\\", "/")
    lowered = raw.lower()
    by_name = dict(_BARE_INSPECT_FILES)
    for name, path in _BARE_INSPECT_FILES:
        if name in lowered:
            return path
    if re.search(r"(?i)\btool_subset\b", raw):
        return by_name["tool_subset.py"]
    if _INSPECT_DRIVE.search(raw):
        return by_name["drive.py"]
    if _INSPECT_CONFIRM.search(raw):
        return by_name["policy.py"]
    if _INSPECT_PHYSICS.search(raw):
        return PHYSICS_INSPECT_PATH
    if _INSPECT_HOW_YOU_WORK.search(raw):
        return _HOW_YOU_WORK_PATH
    return None


def inspect_path_guide() -> str:
    """One path map for skill cards. Built from the same table as inspect_read_path."""
    by_name = dict(_BARE_INSPECT_FILES)
    return (
        f"confirm → {by_name['policy.py']}; "
        f"tool_subset → {by_name['tool_subset.py']}; "
        f"Drive strip → {by_name['drive.py']}; "
        f"solar / space sim → {PHYSICS_INSPECT_PATH} "
        f"(+ {', '.join(PHYSICS_INSPECT_FANOUT[1:])}); "
        f"how you work → {_HOW_YOU_WORK_PATH}; "
        "a named arelis/ or docs/ path → that path."
    )


_INSPECT_NUDGE = (
    "Intent preflight: they asked how she works or to read her source. "
    "Call workspace(action=read) on {path}. "
    "If several files are needed, list one folder then fanout-read; "
    "do not list the workspace root. "
    "Quote function names, gates, and paths from the tool result. "
    "Do not invent. Do not recall the package. Do not web_search. "
    "This is read-only. Writes still need Allow. "
    "Do not ask permission in chat."
)
_INSPECT_PHYSICS_NUDGE = (
    "Intent preflight: they asked to assess the solar-system sim from source. "
    "Do not list the workspace root. "
    "In one fanout, workspace(action=read) on "
    + ", ".join(PHYSICS_INSPECT_FANOUT)
    + ". "
    "Quote the integrator, GM/constant provenance, and IC source "
    "(Horizons VECTORS — bodies where they are now, not a homemade catalog). "
    "scene.py may truncate; horizons.py is the IC contract. "
    "Do not invent. Do not recall the package. Do not web_search. "
    "This is read-only. Writes still need Allow. "
    "Do not ask permission in chat."
)


def inspect_preflight_nudge(text: str) -> str:
    """Path-named inspect nudge. Preflight uses this; do not copy the template."""
    raw = text or ""
    if _INSPECT_PHYSICS.search(raw):
        return _INSPECT_PHYSICS_NUDGE
    path = inspect_read_path(raw) or "the arelis/ or docs/ path they named"
    return _INSPECT_NUDGE.format(path=path)


@dataclass(frozen=True)
class _InspectReadSpec(IntentSpec):
    """Inspect reads; write verbs never match (inspect_write wins)."""

    def matches(self, text: str) -> bool:
        return looks_like_source_inspect(text)


INSPECT_WRITE = IntentSpec(
    kind="inspect_write",
    patterns=(_SOURCE_WRITE,),
    expected_tools=("workspace",),
    nudge=(
        "Intent preflight: this is a write to her source. "
        "Call workspace with action=write or action=edit. "
        "Allow still applies. Do not silently edit. "
        "Do not ask permission in chat."
    ),
    schema_tools=frozenset({"workspace", "git_info"}),
    auto_hint=True,
)

INSPECT = _InspectReadSpec(
    kind="inspect",
    patterns=_INSPECT_PATTERNS,
    expected_tools=("workspace",),
    nudge=_INSPECT_NUDGE.format(path="the mapped path"),
    schema_tools=frozenset({"workspace", "git_info"}),
    auto_hint=True,
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
    DOCUMENT,
    DOCS,
    PLOT,
    SOLAR_BODY,
    SOLAR_STATUS,
    EARTH_STATUS,
    SCIENCE_CATALOG,
    DIAGNOSTICS,
    RUN_SCRIPT,
    WATCH,
    INSPECT_WRITE,
    INSPECT,
)

BY_KIND: dict[str, IntentSpec] = {s.kind: s for s in CATALOG}

AUTO_HINTS: tuple[IntentSpec, ...] = tuple(s for s in CATALOG if s.auto_hint)

FULL_SURFACE_KINDS = frozenset(s.kind for s in CATALOG if s.full_surface)

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


def weather_intent_matches(text: str) -> bool:
    """True for a forecast ask, not a device spec that mentions temperature."""
    raw = text or ""
    if exactness_match("weather", raw):
        return True
    if not WEATHER.matches(raw):
        return False
    return not _WEATHER_SPEC_VETO.search(raw)


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


def looks_like_local_clock_ask(text: str) -> bool:
    """True when now_line already answers — local time/date, not a meeting."""
    return bool(_LOCAL_CLOCK.match((text or "").strip()))


def looks_like_identity_ask(text: str) -> bool:
    """True when they are asking who Arelis is, not who is on screen."""
    return bool(_IDENTITY_ASK.match((text or "").strip()))


def is_tiny_prompt_ask(text: str) -> bool:
    """Clock, hello, thanks, or identity — no web fallback.

    Unmatched real work still fail-opens. A place ("what time is it in Tokyo")
    does not match: that still needs a tool. "Who is this" is not identity.
    """
    from arelis.core.sms_complete import (
        looks_like_closing_chitchat,
        looks_like_greeting,
    )

    raw = (text or "").strip()
    if not raw:
        return False
    return (
        looks_like_local_clock_ask(raw)
        or looks_like_greeting(raw)
        or looks_like_closing_chitchat(raw)
        or looks_like_identity_ask(raw)
    )
