"""Fill send_sms (to, body) from the current turn and recent chat.

Small models often split "text Brian" and "say I'm late" across turns, then
re-ask for the body forever. This module reconstructs a draft so preflight and
the agent loop can nudge with concrete args — still never sends without Allow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arelis.contacts import Contact, load_contacts, match_contact_label, resolve_contact
from arelis.history_view import history_pairs

# Same family as preflight, kept here so completion owns the parse.
# Name group allows "wife and daughter" / "Sam, Robin" before the body marker.
# "text message" must beat bare "text", or "text message to my wife" parses
# as send_sms(to="message"). STT often drops "send a" and starts "in a text…".
_SMS_SEND = re.compile(
    r"(?i)\b(?:"
    r"(?:in\s+a\s+)?text\s+message|"
    # Sherpa often hears "send a text" as "senatic's" / "semantic's".
    r"senatic'?s?\s+message|"
    r"semantic'?s?\s+message|"
    r"sendatic'?s?\s+message|"
    r"sms|txt|"
    # Longer "send a text message" before bare "send a text" / "send message".
    r"send\s+(?:a\s+)?(?:text\s+message|text|sms|message)|"
    r"message(?=\s+to\b)|"
    # "send her another text …" / "send him a message …"
    r"send\s+(?:her|him|them)\s+(?:(?:an?\s+|another\s+|a\s+)?"
    r"(?:text\s+message|text|sms|message))|"
    r"text"
    r")\s+"
    r"(?:to\s+)?"
    r"(?P<to>(?:my\s+)?[A-Za-z][A-Za-z0-9_.\-]{0,40}"
    r"(?:\s+(?:and|&|,)\s+(?:my\s+)?[A-Za-z][A-Za-z0-9_.\-]{0,40}){0,4}"
    r"(?:\s+(?!that\b|saying\b|and\b|&\b|to\b|tell|just\b)[A-Za-z][A-Za-z0-9_.\-]{0,40}){0,3})"
    r"(?:\s*(?::|that|saying|,|"
    r"and\s+have\s+it\s+say|"
    r"have\s+it\s+say|"
    r"and\s+say|"
    r"and\s+(?:just\s+|please\s+)?tell(?:ing)?\s+(?:him|her|them)|"
    r"(?:just\s+|please\s+)?tell(?:ing)?\s+(?:him|her|them))\s*(?P<body>.+))?"
)

# "Send her another text and tell her that …" — recipient is the pronoun.
_PRONOUN_SMS = re.compile(
    r"(?i)\b(?:"
    r"send\s+(?P<pronoun>her|him|them)\s+(?:(?:an?\s+|another\s+|a\s+)?"
    r"(?:text\s+message|text|sms|message))|"
    r"text\s+(?P<pronoun2>her|him|them)\b|"
    r"send\s+(?:her|him|them)\s+another\s+text\b"
    r")"
    r"(?:\s+(?:and\s+)?(?:just\s+|please\s+)?tell\s+(?:him|her|them)\s+(?P<body>.+)"
    r"|\s+(?:that|saying|:)\s*(?P<body2>.+))?"
)

# Trailing "… and tell him I love you" when the main regex left body empty.
# Voice often inserts "just": "and just tell her good night".
_TELL_HIM_BODY = re.compile(
    r"(?is)\s+(?:and\s+)?(?:just\s+|please\s+)?tell(?:ing)?\s+(?:him|her|them)\s+(.+)$"
)
_HAVE_IT_SAY = re.compile(
    r"(?is)\s+(?:and\s+)?have\s+it\s+say\s+(.+)$"
)

# "open x.com" / "OpenX.com" / bare URLs must never become an SMS body.
_BROWSER_OR_URL = re.compile(
    r"(?i)^\s*(?:"
    r"(?:re-?)?open\s*x\.?\s*com\b|"
    r"openx\.com\b|"
    r"(?:re-?)?open\s+(?:up\s+)?(?:https?://\S+|(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b|"
    r"x\.com|twitter|youtube|gmail|github|google|reddit)\b|"
    r"go\s+to\s+(?:https?://\S+|x\.com|(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b)|"
    r"pull\s+up\s+\S+|"
    r"(?:https?://|www\.)\S+|"
    r"(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b"
    r")"
)


_BODY_WRAPPER = re.compile(
    r"(?is)^\s*(?:"
    r"i\s+want\s+(?:it|you|me)\s+to\s+say|"
    r"i\s+want\s+(?:the\s+)?(?:text\s+)?(?:message|sms|text)\s+to|"
    r"i\s+want\s+the\s+text\s+message\s+to|"
    r"tell\s+(?:them|her|him|everyone)|"
    r"(?:the\s+)?(?:message|text|body)\s+(?:is|should\s+be|should\s+say)|"
    r"make\s+it\s+say|"
    r"just\s+say"
    r")\s+[.:,\-]?\s*"
)

_SKIP_TO = frozenset(
    {
        "me",
        "him",
        "her",
        "them",
        "someone",
        "back",
        "again",
        "later",
        "just",
        "please",
        "also",
        "only",
        "now",
        "tell",
        "telling",
        "say",
        "saying",
        "have",
    }
)

# "write a text file" / "text file named…" must never become send_sms(to="file").
# Channel nouns: "text message to my wife" must never become send_sms(to="message").
_FS_TO_BLOCK = frozenset(
    {
        "file",
        "files",
        "folder",
        "directory",
        "path",
        "readme",
        "temp",
        "tmp",
        "document",
        "doc",
        "note",
        "notes",
        "message",
        "messages",
        "sms",
        "txt",
        "text",
    }
)

_WORKSPACE_WRITE = re.compile(
    r"(?i)\b("
    r"(?:write|create|save|make)\s+(?:a\s+|an\s+|the\s+|me\s+a\s+)?"
    r"(?:temp\s+|temporary\s+|text\s+|new\s+)?"
    r"(?:file|folder|directory|readme|note|document)"
    r"|"
    r"(?:write|save)\s+(?:this\s+|it\s+)?(?:to|into)\s+\S+"
    r"|"
    r"workspace\s+(?:write|edit|save)"
    r")\b"
)

_GOALS_UTTERANCE = re.compile(
    r"(?i)\b("
    r"(?:what(?:'s|\s+are)|show(?:\s+me)?|list)\s+(?:my\s+)?(?:goals?|commitments?)|"
    r"(?:add|set|create)\s+(?:a\s+)?(?:goal|commitment)|"
    r"(?:mark|set)\s+(?:that\s+|the\s+|my\s+)?(?:goal|commitment)\s+"
    r"(?:as\s+)?(?:done|complete|completed)|"
    r"(?:complete|finish)\s+(?:that\s+|the\s+|my\s+)?(?:goal|commitment)|"
    r"(?:delete|remove|drop|pause|resume)\s+"
    r"(?:that\s+|the\s+|this\s+|my\s+|both\s+(?:of\s+)?(?:those\s+|the\s+)?)?"
    r"(?:goals?|commitments?)"
    r")\b"
)

_TASKS_UTTERANCE = re.compile(
    r"(?i)\b("
    r"(?:what(?:'s|\s+are)|show(?:\s+me)?|list)\s+(?:my\s+)?(?:tasks?|to-?dos?|checklist)|"
    r"(?:add|create)\s+(?:a\s+)?(?:task|to-?do)|"
    r"(?:mark|complete|finish|remove|delete)\s+(?:the\s+|my\s+|that\s+)?"
    r"(?:task|to-?do)"
    r")\b"
)

_MEMORY_UTTERANCE = re.compile(
    r"(?i)\b("
    r"remember\s+that|"
    r"forget\s+(?:that|the|this|my)|"
    r"what\s+fruit\s+did\s+i|"
    r"favorite\s+test\s+fruit|"
    r"store\s+(?:this|that)\s+(?:fact|preference)"
    r")\b"
)

_CONTACTS_UTTERANCE = re.compile(
    r"(?i)\b("
    r"who\s+is\s+my\s+\w+\s+in\s+(?:my\s+)?contacts|"
    r"who\s+is\s+my\s+(?:wife|husband|mom|mother|dad|father|daughter|son|"
    r"brother|sister)\b|"
    r"my\s+(?:wife|husband|mom|mother|dad|father|daughter|son|"
    r"brother|sister)'?s?\s+(?:phone|number|email)|"
    r"(?:in|from|via)\s+(?:my\s+)?contacts|"
    r"look\s+up\s+(?:in\s+)?contacts|"
    r"contact\s+(?:for|named|book)|"
    r"(?:her|his|their)\s+(?:phone|number|email)|"
    r"what(?:'s|\s+is)\s+(?:her|his|their)\s+phone|"
    r"what(?:'s|\s+is)\s+my\s+\w+'?s?\s+phone"
    r")\b"
)

_CONTACTS_PROCEED = re.compile(
    r"(?i)^\s*(?:proceed|go\s+ahead|do\s+it|yes|yeah|yep|please|ok(?:ay)?)\.?\s*$"
)

_CONTACT_PHONE_ASK = re.compile(
    r"(?i)\b("
    r"(?:her|his|their)\s+(?:phone|number|email)|"
    r"my\s+\w+'?s?\s+(?:phone|number|email)|"
    r"phone\s+number|"
    r"what(?:'s|\s+is).{0,32}\b(?:phone|number|email)"
    r")\b"
)

_CONTACT_EMAIL_ASK = re.compile(r"(?i)\bemail\b")

_CLOSING_CHITCHAT = re.compile(
    r"(?i)^\s*(?:(?:alright|all\s+right|ok(?:ay)?|yes|yeah|yep|sure|nope)[,.]?\s*)*"
    r"(?:thank\s+you|thanks|ty|bye|goodbye|that'?s\s+(?:all|it)|never\s*mind|"
    r"(?:excellent|great|good|nice)\s+job\b.*|"
    r"that will be all)"
    r"[.!\s]*$"
)

# Greetings must never complete or revive a send. "how are you today?" used
# to arm the full tool list (bare "today" looked like news) and the 7B
# replayed the last SMS draft.
_GREETING = re.compile(
    r"(?i)^\s*(?:"
    r"hi|hello|hey|yo|howdy|sup|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"how\s+are\s+you(?:\s+(?:today|tonight|doing(?:\s+today|\s+tonight)?))?"
    r"|how'?s\s+it\s+going"
    r"|what'?s\s+up"
    r")[?!.\s]*$"
)

# Image generation must never revive a stale SMS draft as its "body".
# Also blocks "text to image" from parsing as send_sms(to="image").
_IMAGE_GEN = re.compile(
    r"(?i)("
    r"\b(?:generate|create|make|draw|render)\s+"
    r"(?:(?:an?\s+|the\s+|this\s+|me\s+(?:an?\s+)?)?"
    r"(?:new\s+|another\s+|second\s+|different\s+|happier\s+|cute\s+)*)?"
    r"(?:image|picture|photo|png|illustration)\b|"
    r"\b(?:new|another)\s+(?:image|picture|photo)\b|"
    r"\btext[\s\-]?to[\s\-]?image\b|"
    r"\bcomfy(?:ui)?\b|"
    r"\b(?:open|start|launch)\s+comfy(?:ui)?\b"
    r")"
)

# Arithmetic asks. A cancelled SMS turn leaves "text my wife …" in history, and
# the next turn ("what is 17 times 19?") must not be read as the body of it, nor
# arm the send surface. Anchored: "text Brian that 2 + 2 = 4" is still an SMS.
_MATH_ASK = re.compile(
    r"(?i)^\s*(?:hey\s+arelis[\s,.!]*)?(?:"
    r"(?:what(?:'s|\s+is)\s+)?-?\d[\d,.]*\s*"
    # The multiplication and division signs are in this class because people
    # type them. Ruff calls the multiplication sign ambiguous with a letter x,
    # which is exactly true and exactly why both spellings are listed.
    r"(?:[-+*/^x×÷]|times|plus|minus|divided\s+by|over|mod|"  # noqa: RUF001
    r"to\s+the\s+power(?:\s+of)?)\s*-?\d"
    r"|(?:what(?:'s|\s+is)|calculate|compute|work\s+out|solve|how\s+much\s+is)\b"
    r"[^?]{0,60}?\b(?:\d+\s*"
    r"(?:[-+*/^x×÷]|times|plus|minus|divided\s+by|percent\s+of)\s*\d"  # noqa: RUF001
    r"|square\s+root\b|factorial\b)"
    r")"
)

_EXPLICIT_SMS_VERB = re.compile(
    r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message)|"
    r"senatic'?s?|semantic'?s?|message\s+to)\b"
)

_ASKED_FOR_BODY = re.compile(
    r"(?i)\b("
    r"what\s+(should|do)\s+(i|you)\s+(say|text|send)|"
    r"what('s| is)\s+the\s+(message|text|body)|"
    r"what\s+do\s+you\s+want\s+(it|me)\s+to\s+say|"
    r"message\s+should\s+i\s+send|"
    r"tell\s+me\s+what\s+to\s+(say|text)"
    r")\b"
)

_SMS_VERB = re.compile(
    r"(?i)^\s*(text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message)|"
    r"senatic'?s?|semantic'?s?|message\s+to)\b"
)

# Revive a prior complete draft when the user just confirms send.
_SEND_CONFIRM = re.compile(
    r"(?i)^\s*("
    r"send\s+(?:the\s+)?(?:text|sms|message|it|that)|"
    r"send\s+it\s+(?:now|please)?|"
    r"(?:yes|yep|yeah|ok|okay|go\s+ahead|do\s+it|please)"
    r"(?:\s*,?\s*please)?|"
    r"yes\s*,?\s*please|"
    r"please\s+send(?:\s+it)?"
    r")\s*[.!]?\s*$"
)

_PROCEED_ASK = re.compile(
    r"(?i)\b("
    r"would\s+you\s+like\s+(?:me\s+)?to\s+send|"
    r"shall\s+i\s+send|"
    r"want\s+me\s+to\s+send|"
    r"confirm(?:ation)?|"
    r"proceed\s+with\s+sending"
    r")\b"
)


@dataclass(frozen=True)
class SmsDraft:
    to: str
    body: str
    alias: str = ""
    source: str = "current"
    # Extra recipients after the primary `to` (multi-send). Empty for one person.
    recipients: tuple[str, ...] = ()
    # Book aliases aligned with recipients ("" when unresolved).
    aliases: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Ready to send when body is set; multi-recipient needs every alias."""
        if not self.body.strip():
            return False
        names = self.all_tos
        if not names:
            return False
        # Single recipient: allow unresolved names (send_sms resolves at send time).
        if len(names) == 1:
            return True
        # Multi: every name must be in contacts before we force/send any of them.
        if self.missing:
            return False
        return len(self.resolved_aliases) == len(names)

    @property
    def all_tos(self) -> tuple[str, ...]:
        if self.recipients:
            return self.recipients
        primary = self.to.strip()
        return (primary,) if primary else ()

    @property
    def resolved_aliases(self) -> tuple[str, ...]:
        if self.aliases:
            return tuple(a for a in self.aliases if a)
        if self.alias:
            return (self.alias,)
        return ()

    @property
    def tool_to(self) -> str:
        """Preferred `to` arg for the next send_sms (first unresolved→resolved)."""
        resolved = self.resolved_aliases
        if resolved:
            return resolved[0]
        return self.alias or self.to.strip()


def _soften_caps(text: str) -> str:
    """Sherpa ALL-CAPS lines still have to parse as normal speech."""
    raw = (text or "").strip()
    letters = [c for c in raw if c.isalpha()]
    if len(letters) < 6:
        return raw
    if (sum(1 for c in letters if c.isupper()) / len(letters)) < 0.8:
        return raw
    return raw[0].upper() + raw[1:].lower()


def _clean_to(raw: str) -> str:
    return (raw or "").strip().rstrip(".,!;:")


def _clean_body(raw: str) -> str:
    text = (raw or "").strip()
    # Strip meta wrappers so "i want it to say everything will be okay"
    # becomes the actual SMS body (U6 / operator session).
    prev = None
    while prev != text:
        prev = text
        text = _BODY_WRAPPER.sub("", text).strip()
    # Strip wrapping quotes the user typed around the message.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _split_recipients(raw: str) -> list[str]:
    text = _clean_to(raw)
    if not text:
        return []
    parts = re.split(r"(?i)\s*(?:,|&|\band\b)\s*", text)
    out: list[str] = []
    for part in parts:
        name = _clean_to(part)
        # Drop a leading "my " so "my wife" → "wife" for alias resolve.
        if name.lower().startswith("my "):
            name = name[3:].strip()
        first = name.split()[0].lower() if name else ""
        if not name or first in _SKIP_TO or first in _FS_TO_BLOCK:
            continue
        if name not in out:
            out.append(name)
    return out


def resolve_sms_alias(
    to: str, contacts: dict[str, Contact] | None = None
) -> str:
    """Map a spoken name to a contacts.yaml alias when possible."""
    book = contacts if contacts is not None else load_contacts()
    cleaned = _clean_to(to)
    parts = cleaned.split()
    # Multi-token ("Sam Brightley"): never let a short alias like `sam` on `me`
    # substring-steal via match_contact_label. Exact keys, then fuzzy last name.
    if len(parts) >= 2:
        hit = resolve_contact(to, book)
        if hit is not None:
            return hit.alias
        key = cleaned.lower()
        for contact in book.values():
            if _clean_to(contact.name).lower() == key:
                return contact.alias
            if _clean_to(contact.alias).lower() == key:
                return contact.alias
            if any(_clean_to(a).lower() == key for a in contact.aliases):
                return contact.alias
        fuzzy = _fuzzy_person_match(cleaned, book)
        return fuzzy.alias if fuzzy is not None else ""

    hit = resolve_contact(to, book)
    if hit is not None:
        return hit.alias
    labeled = match_contact_label(to, book)
    if labeled is not None:
        return labeled.alias
    # Single token: first-name match, but prefer non-`me` when several match.
    first = parts[0].lower() if parts else ""
    if first and len(first) >= 2:
        hits: list[Contact] = []
        for contact in book.values():
            if first in contact.keys:
                hits.append(contact)
                continue
            name_first = (contact.name or "").split()[0].lower()
            if name_first and name_first == first:
                hits.append(contact)
        if not hits:
            return ""
        non_me = [c for c in hits if c.alias != "me"]
        pick = non_me[0] if non_me else hits[0]
        return pick.alias
    return ""


def _edit_distance(a: str, b: str) -> int:
    """Small Levenshtein for last-name typos (Brightley ↔ Brightly)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _fuzzy_person_match(to: str, book: dict[str, Contact]) -> Contact | None:
    """Match multi-token names with a one/two-edit last-name tolerance."""
    parts = _clean_to(to).lower().split()
    if len(parts) < 2:
        return None
    first, last = parts[0], parts[-1]
    best: Contact | None = None
    best_dist = 99
    for contact in book.values():
        candidates = [contact.name, contact.alias, *contact.aliases]
        for cand in candidates:
            cparts = _clean_to(cand).lower().split()
            if len(cparts) < 2:
                continue
            if cparts[0] != first:
                continue
            dist = _edit_distance(last, cparts[-1])
            if dist <= 2 and dist < best_dist:
                best = contact
                best_dist = dist
    return best


def _bind_recipients(
    names: list[str], book: dict[str, Contact]
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (primary_to, primary_alias, recipients, aliases, missing)."""
    if not names:
        return "", "", (), (), ()
    aliases: list[str] = []
    missing: list[str] = []
    for name in names:
        alias = resolve_sms_alias(name, book)
        aliases.append(alias)
        if not alias:
            missing.append(name)
    primary = names[0]
    return primary, aliases[0], tuple(names), tuple(aliases), tuple(missing)


def looks_like_workspace_write(text: str) -> bool:
    """True when the utterance is about creating/editing a file, not SMS."""
    return bool(_WORKSPACE_WRITE.search(text or ""))


def looks_like_goals_utterance(text: str) -> bool:
    """True when the utterance is about listing/updating goals, not SMS body."""
    return bool(_GOALS_UTTERANCE.search(text or ""))


def looks_like_tasks_utterance(text: str) -> bool:
    """True when the utterance is about to-dos, not an SMS body."""
    return bool(_TASKS_UTTERANCE.search(text or ""))


def looks_like_memory_utterance(text: str) -> bool:
    """True for remember/forget turns that must not revive a pending SMS."""
    return bool(_MEMORY_UTTERANCE.search(text or ""))


def looks_like_contacts_utterance(text: str) -> bool:
    """True for contact-book lookups that must not revive a pending SMS."""
    return bool(_CONTACTS_UTTERANCE.search(text or ""))


def looks_like_contact_email_ask(text: str) -> bool:
    raw = text or ""
    return bool(_CONTACT_EMAIL_ASK.search(raw)) and not bool(
        re.search(r"(?i)\bphone\b", raw)
    )


def looks_like_contact_phone_ask(text: str) -> bool:
    """True when they asked for a number, not the whole contact card."""
    if looks_like_contact_email_ask(text):
        return False
    return bool(_CONTACT_PHONE_ASK.search(text or ""))


def looks_like_contacts_followup(
    text: str, history: list[Any] | None = None
) -> bool:
    """True for 'proceed' after a contacts lookup that never called the tool."""
    if not _CONTACTS_PROCEED.match((text or "").strip()):
        return False
    for item in reversed(history or []):
        role = getattr(item, "role", None) or (
            item.get("role") if isinstance(item, dict) else ""
        )
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if str(role) == "user" and looks_like_contacts_utterance(str(content or "")):
            return True
    return False


_LOOK_OR_FILE = re.compile(
    r"(?i)\b("
    r"look at this|"
    r"look at the|"
    r"using the camera|"
    r"with vision|"
    r"ocr this|"
    r"describe (?:the|this|that) (?:image|file|diagram|picture|photo)|"
    r"what(?:'s| is) in (?:this|the|that) (?:image|screenshot|photo|picture|pic)|"
    r"what in this|"
    r"what's in this|"
    r"summarize (?:the|this|that) file|"
    r"git status|"
    r"what(?:'s| is) on my clipboard|"
    r"generate (?:a |an |me )?(?:simple )?image"
    r")\b"
)


def looks_like_look_or_file(text: str) -> bool:
    """True for vision / OCR / attach / git / clipboard turns — not an SMS body."""
    return bool(_LOOK_OR_FILE.search(text or ""))


def looks_like_greeting(text: str) -> bool:
    """True for hello / how-are-you — not an SMS body and not a news ask."""
    return bool(_GREETING.match((text or "").strip()))


def looks_like_math_ask(text: str) -> bool:
    """True for arithmetic turns that must not revive or feed an SMS draft."""
    return bool(_MATH_ASK.match(_soften_caps((text or "").strip())))


def sms_intent_this_turn(text: str) -> bool:
    """True only when *this* utterance is a send (or inbound) SMS ask.

    History must not authorize a send. A leftover grocery draft in an older
    turn is not an intent on "how are you today?".
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if looks_like_greeting(raw) or looks_like_closing_chitchat(raw):
        return False
    if looks_like_stale_sms_skip(raw):
        return False
    if _EXPLICIT_SMS_VERB.match(raw) or _SMS_VERB.match(raw):
        return True
    return parse_sms_utterance(raw) is not None


_DESCRIBE_FOLLOWUP = re.compile(
    r"(?i)^\s*(?:please\s+|just\s+)*(?:describe|tell me about)\s+"
    r"(?:it|that|this)\b"
)


def looks_like_describe_followup(text: str) -> bool:
    """True for 'just describe it' after a failed image — not an SMS body."""
    return bool(_DESCRIBE_FOLLOWUP.match((text or "").strip()))


def looks_like_stale_sms_skip(
    text: str, history: list[Any] | None = None
) -> bool:
    """True when this turn is clearly not the body of a pending SMS draft."""
    return (
        looks_like_greeting(text)
        or looks_like_math_ask(text)
        or looks_like_closing_chitchat(text)
        or looks_like_goals_utterance(text)
        or looks_like_tasks_utterance(text)
        or looks_like_memory_utterance(text)
        or looks_like_contacts_utterance(text)
        or looks_like_contacts_followup(text, history)
        or looks_like_workspace_write(text)
        or looks_like_image_gen(text)
        or looks_like_describe_followup(text)
        or looks_like_browser_or_url(text)
        or looks_like_look_or_file(text)
    )


def looks_like_closing_chitchat(text: str) -> bool:
    """True for short thanks/bye turns that must not revive weather/SMS tools."""
    return bool(_CLOSING_CHITCHAT.match((text or "").strip()))


def looks_like_image_gen(text: str) -> bool:
    """True when the utterance is Comfy/image generate, not an SMS body."""
    raw = text or ""
    from arelis.attachments import split_attachments_turn, wants_image_edit

    _block, ask = split_attachments_turn(raw)
    check = ask or raw
    # Edit phrasing ("make this more vibrant") must not count as generate.
    if wants_image_edit(check):
        return False
    return bool(_IMAGE_GEN.search(check))


def looks_like_browser_or_url(text: str) -> bool:
    """True for open-site / URL turns that must not revive a pending SMS draft."""
    return bool(_BROWSER_OR_URL.match((text or "").strip()))


def _last_sms_alias_from_history(
    history: list[Any] | None,
    book: dict[str, Contact],
) -> str:
    """Most recent send_sms recipient alias from prior user SMS drafts."""
    for role, content in reversed(history_pairs(history or [])):
        if role != "user":
            continue
        prior = parse_sms_utterance(content)
        if prior is None:
            continue
        names = list(prior.all_tos)
        if not names:
            continue
        # Skip unresolved pronouns in the prior turn itself.
        if names[0].lower() in {"her", "him", "them"}:
            continue
        draft = _finalize_draft(
            names=names, body=prior.body or "x", source="history", book=book
        )
        if draft.tool_to:
            return draft.tool_to
        if draft.alias:
            return draft.alias
    return ""


def parse_sms_utterance(text: str) -> SmsDraft | None:
    """Parse a single user utterance into an SMS draft (maybe incomplete)."""
    raw = _soften_caps((text or "").strip())
    if not raw:
        return None
    # File-write phrasing that happens to contain "text" must not become SMS.
    if looks_like_workspace_write(raw) and not _EXPLICIT_SMS_VERB.match(raw):
        return None
    # OCR / "read the text in this screenshot" / text-file — not a send.
    from arelis.core.skills import sms_negative_hit

    if sms_negative_hit(raw) and not _EXPLICIT_SMS_VERB.match(raw):
        return None
    # Calendar create/reminder that mentions "text my wife" is agenda, not SMS.
    from arelis.core.agenda_complete import looks_like_calendar_create

    if looks_like_calendar_create(raw) and not _EXPLICIT_SMS_VERB.match(raw):
        return None
    # "text to image …" matches _SMS_SEND as to="image" — never treat as SMS.
    if re.search(r"(?i)\btext[\s\-]?to[\s\-]?image\b", raw):
        return None

    # Pronoun recipient: "send her another text and tell her that …"
    pro = _PRONOUN_SMS.search(raw)
    if pro:
        pronoun = (pro.group("pronoun") or pro.group("pronoun2") or "her").lower()
        body = _clean_body(pro.group("body") or pro.group("body2") or "")
        if not body:
            tell = _TELL_HIM_BODY.search(raw[pro.start() :])
            if tell:
                body = _clean_body(tell.group(1) or "")
        return SmsDraft(
            to=pronoun,
            body=body,
            source="current",
            recipients=(pronoun,),
        )

    match = _SMS_SEND.search(raw)
    if not match:
        return None
    to_raw = match.group("to") or ""
    body = _clean_body(match.group("body") or "")
    # Voice: "text my wife and say, hey grocery test"
    say_split = re.search(r"(?i)^(.+?)\s+and\s+say\s*,?\s*(.*)$", to_raw)
    if say_split:
        to_raw = say_split.group(1).strip()
        extra = _clean_body(say_split.group(2) or "")
        if extra and not body:
            body = extra
    elif re.search(r"(?i)\band\s+say$", to_raw):
        to_raw = re.sub(r"(?i)\s+and\s+say$", "", to_raw).strip()
    names = _split_recipients(to_raw)
    if not body:
        # "… to Sam Brightley and tell him I love him"
        tell = _TELL_HIM_BODY.search(raw[match.start() :])
        if tell:
            body = _clean_body(tell.group(1) or "")
    if not body:
        have_say = _HAVE_IT_SAY.search(raw[match.start() :])
        if have_say:
            body = _clean_body(have_say.group(1) or "")
            to_raw = re.sub(r"(?i)\s+and\s+have$", "", to_raw).strip()
            names = _split_recipients(to_raw)
    if not names:
        return None
    primary = names[0]
    return SmsDraft(
        to=primary,
        body=body,
        source="current",
        recipients=tuple(names),
    )


def _finalize_draft(
    *,
    names: list[str],
    body: str,
    source: str,
    book: dict[str, Contact],
) -> SmsDraft:
    primary, alias, recipients, aliases, missing = _bind_recipients(names, book)
    return SmsDraft(
        to=primary,
        body=body,
        alias=alias,
        source=source,
        recipients=recipients,
        aliases=aliases,
        missing=missing,
    )


def complete_sms_draft(
    user_text: str,
    *,
    history: list[Any] | None = None,
    contacts: dict[str, Contact] | None = None,
) -> SmsDraft | None:
    """Best draft for this turn: current utterance, or to/body merged from history."""
    book = contacts if contacts is not None else load_contacts()
    current = parse_sms_utterance(user_text)

    def _resolve_pronoun_names(names: list[str]) -> list[str]:
        if not names:
            return names
        if names[0].lower() not in {"her", "him", "them"}:
            return names
        alias = _last_sms_alias_from_history(history, book)
        return [alias] if alias else names

    if current and current.body and current.all_tos:
        names = _resolve_pronoun_names(list(current.all_tos))
        draft = _finalize_draft(
            names=names,
            body=current.body,
            source="current",
            book=book,
        )
        if draft.complete or draft.missing:
            return draft

    pairs = history_pairs(history or [])
    # Include the current user text as the newest user turn for merging.
    # (AgentLoop adds the user message before we read history, so it may already
    # be the last entry — dedupe by comparing content.)
    if not pairs or pairs[-1] != ("user", user_text):
        pairs = [*pairs, ("user", user_text)]

    # Case A: current turn is a full SMS parse with to but empty body — keep looking
    # for a following body is N/A (this IS the current turn). Incomplete.
    if current and not current.body:
        names = _resolve_pronoun_names(list(current.all_tos))
        return _finalize_draft(
            names=names,
            body="",
            source="current",
            book=book,
        )

    # Case C: "yes please" / "send it" after a prior complete SMS draft.
    if current is None and _SEND_CONFIRM.match(user_text or ""):
        saw_ask = False
        for role, content in reversed(pairs[:-1]):
            if role == "assistant" and (
                _ASKED_FOR_BODY.search(content or "")
                or _PROCEED_ASK.search(content or "")
            ):
                saw_ask = True
                continue
            if role == "user":
                prior = parse_sms_utterance(content)
                if prior and prior.all_tos and prior.body:
                    # Bare "yes" after a non-SMS turn must not revive an older
                    # complete draft — only confirm when the assistant just
                    # asked about sending.
                    if saw_ask:
                        return _finalize_draft(
                            names=list(prior.all_tos),
                            body=prior.body,
                            source="history",
                            book=book,
                        )
                    break
                if prior and prior.all_tos and not prior.body and saw_ask:
                    # Affirm without body — still incomplete.
                    return _finalize_draft(
                        names=list(prior.all_tos),
                        body="",
                        source="history",
                        book=book,
                    )
                if saw_ask:
                    continue
                break

    # Case B: current text is NOT an SMS verb — treat as body after a pending ask.
    if current is None and user_text.strip() and not _SMS_VERB.match(user_text):
        if _SEND_CONFIRM.match(user_text or ""):
            return None
        # Goals / tasks / memory / contacts / file-write / image-gen /
        # calendar / open-URL / analyze turns must not steal a pending SMS.
        from arelis.core.agenda_complete import (
            looks_like_calendar_create,
            looks_like_calendar_delete,
            looks_like_calendar_read,
        )
        from arelis.core.claims import detect_analyze_ask

        if (
            looks_like_stale_sms_skip(user_text, history)
            or looks_like_calendar_create(user_text)
            or looks_like_calendar_delete(user_text)
            or looks_like_calendar_read(user_text)
            or detect_analyze_ask(user_text)
        ):
            return None
        body = _clean_body(user_text)
        if len(body) < 2:
            return None
        # Never treat a URL-ish string as an SMS body filler.
        if looks_like_browser_or_url(body):
            return None
        # Walk backward: assistant asked for body, then find earlier user "text X".
        pending_names: list[str] = []
        saw_ask = False
        for role, content in reversed(pairs[:-1]):
            if role == "assistant" and _ASKED_FOR_BODY.search(content or ""):
                saw_ask = True
                continue
            if role == "user":
                prior = parse_sms_utterance(content)
                if prior and prior.all_tos and not prior.body:
                    pending_names = list(prior.all_tos)
                    break
                if prior and prior.all_tos and prior.body:
                    # Already had a full draft earlier; only reuse if we saw an ask.
                    if saw_ask:
                        pending_names = list(prior.all_tos)
                    break
                if saw_ask and not prior:
                    # Keep scanning for the text-X turn.
                    continue
        if pending_names:
            return _finalize_draft(
                names=pending_names, body=body, source="history", book=book
            )
        # Also: previous user turn was "text X" with no body, no assistant ask
        # (model stalled). Merge current as body.
        for role, content in reversed(pairs[:-1]):
            if role != "user":
                if role == "assistant":
                    break
                continue
            prior = parse_sms_utterance(content)
            if prior and prior.all_tos and not prior.body:
                return _finalize_draft(
                    names=list(prior.all_tos),
                    body=body,
                    source="history",
                    book=book,
                )
            break

    if current:
        return _finalize_draft(
            names=list(current.all_tos),
            body=current.body,
            source=current.source,
            book=book,
        )
    return None


def normalize_sms_args(args: dict[str, Any]) -> dict[str, Any]:
    """Alias message/text → body; take first resolvable recipient from multi-to."""
    out = dict(args)
    body = str(out.get("body") or "").strip()
    if not body:
        for key in ("message", "text", "sms", "content"):
            alt = str(out.get(key) or "").strip()
            if alt:
                out["body"] = alt
                break
    to_raw = str(out.get("to") or "").strip()
    if to_raw and ("," in to_raw or " and " in to_raw.lower()):
        parts = re.split(r"\s*(?:,|\band\b)\s*", to_raw, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p and p.strip()]
        if parts:
            out["to"] = parts[0]
            to_raw = parts[0]
    first = to_raw.split()[0].lower() if to_raw else ""
    if first in _FS_TO_BLOCK or first in _SKIP_TO:
        out["to"] = ""
    return out


def draft_send_sms_args(
    draft: SmsDraft,
    *,
    already_sent: set[str] | None = None,
) -> dict[str, Any]:
    """Concrete send_sms kwargs from a complete draft (for inject)."""
    return fill_send_sms_args(
        {}, draft, already_sent=already_sent
    )


def fill_send_sms_args(
    args: dict[str, Any],
    draft: SmsDraft | None,
    *,
    contacts: dict[str, Contact] | None = None,
    already_sent: set[str] | None = None,
) -> dict[str, Any]:
    """Fill to/body on a tool call from a known draft.

    When the draft is complete (to+body), the draft body is locked — the model
    cannot overwrite it with a different invent. Confirm cards therefore show
    the body that will actually send. For multi-recipient drafts, `to` is the
    next unresolved alias not already sent this turn.
    """
    out = normalize_sms_args(args if draft is None else dict(args))
    if draft is None:
        return out
    sent = {s.lower() for s in (already_sent or set())}
    next_to = ""
    for alias in draft.resolved_aliases or ((draft.tool_to,) if draft.tool_to else ()):
        if alias and alias.lower() not in sent:
            next_to = alias
            break
    if not next_to:
        next_to = draft.tool_to

    if draft.complete and draft.body:
        out["body"] = draft.body
        if next_to:
            # Preserve a model `to` that is still one of the intended recipients.
            model_to = str(out.get("to") or "").strip()
            if model_to:
                # Multi-token "robin, wife" already peeled in normalize.
                model_alias = resolve_sms_alias(model_to, contacts) or model_to
                if model_alias.lower() in {
                    a.lower() for a in draft.resolved_aliases
                } and model_alias.lower() not in sent:
                    out["to"] = model_alias
                else:
                    out["to"] = next_to
            else:
                out["to"] = next_to
        return out
    if not str(out.get("body") or "").strip() and draft.body:
        out["body"] = draft.body
    to = str(out.get("to") or "").strip()
    if not to:
        out["to"] = next_to
    elif draft.alias and to.lower() != draft.alias.lower():
        # Prefer the book alias when the model passed a display name we resolved.
        if resolve_contact(to, contacts) is None:
            out["to"] = next_to or draft.alias
    return out


def sms_preflight_nudge(draft: SmsDraft) -> str:
    """System nudge with concrete args (still requires Allow)."""
    if len(draft.all_tos) > 1 and draft.missing:
        miss = ", ".join(draft.missing)
        return (
            "Intent preflight: the user wants to text multiple people, but these "
            f"names are not in contacts.yaml: {miss}. "
            "Ask for the missing number(s) or call contacts(action=add) first. "
            "Do not send to only the resolved recipients until every name is known."
        )
    tos = ", ".join(draft.resolved_aliases) or draft.tool_to
    if draft.complete:
        if len(draft.resolved_aliases) > 1:
            return (
                "Intent preflight: send an SMS to each recipient now. Call send_sms "
                f'once per alias in order ({tos}) with the same body="{draft.body[:300]}". '
                "Do not re-ask for the body. Do not invent text. "
                "Each send needs its own Allow."
            )
        return (
            "Intent preflight: send an SMS now. Call send_sms immediately with "
            f'to="{draft.tool_to}" body="{draft.body[:300]}". '
            "Do not re-ask for the body. Do not only talk about sending. "
            "The confirm card is the Allow step."
        )
    return (
        "Intent preflight: the user wants to text "
        f'"{tos}" but the message body is still missing. '
        "Ask once for the body only, or call send_sms when you have it. "
        "Do not invent the text."
    )


def sms_force_call_notice(
    draft: SmsDraft, *, already_sent: set[str] | None = None
) -> str:
    """User-role nudge when the model tried to finish without calling send_sms."""
    if len(draft.all_tos) > 1 and draft.missing:
        miss = ", ".join(draft.missing)
        return (
            f"Do not send yet — contacts missing for: {miss}. "
            "Resolve every recipient first."
        )
    sent = {s.lower() for s in (already_sent or set())}
    remaining = [a for a in draft.resolved_aliases if a.lower() not in sent]
    target = remaining[0] if remaining else draft.tool_to
    extra = ""
    if len(remaining) > 1:
        extra = f" Then repeat for: {', '.join(remaining[1:])}."
    return (
        "You have not finished send_sms. Call it now with "
        f'to="{target}" body="{draft.body[:300]}".{extra} '
        "Chatting is not sending. The confirm card will ask the user to Allow."
    )
