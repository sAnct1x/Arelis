"""Is this turn about something other than the thing you are holding?

These are the "not that" guards. None of them decides what a turn *is*; each
answers whether a turn is a greeting, arithmetic, a file write, a goals ask, a
URL, an image generation — one of the things that must not be mistaken for the
body of a half-finished message, or arm a tool surface that has nothing to do
with it.

They lived in ``sms_complete`` because SMS is where each one was first needed,
and that is a bad address for them twice over. The smaller cost is that the
fattest module in ``core`` got fatter every time a new phrasing turned up. The
larger one is the import it forced: ``intent_catalog.is_tiny_prompt_ask`` —
whose whole job is deciding that a turn needs no tools at all — reached into
the SMS draft reconstructor to find out whether someone had said hello.

Nothing here knows about SMS, and nothing here should learn. A guard that has
to ask "but is it a text message" belongs on the other side of this line.

The attachments imports stay inside the functions on purpose. Several modules
under ``arelis.core`` import ``arelis.attachments`` while they are themselves
being imported, and a module-level import here closes that loop.
"""

from __future__ import annotations

import re
from typing import Any

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

# How people actually ask, as opposed to how the pattern above was written.
# `_TASKS_UTTERANCE` needs the literal token "task" / "todo" / "checklist",
# so "what do I have **to do** today" — two words — fell through every branch
# of it and reached no rule anywhere in preflight.
#
# Anchored at the start, and that is the whole safety argument. "text my wife
# and tell her I have to do the shopping today" carries the same words in the
# middle of an outbound message, and telling those two apart is why this is a
# start-anchored pattern rather than a wider alternation.
_TASKS_DAY_ASK = re.compile(
    r"(?i)\A\s*(?:so[,\s]+|ok(?:ay)?[,\s]+|hey[,\s]+)?"
    r"(?:"
    r"what\s+do\s+i\s+(?:have|need)\s+to\s+do|"
    r"anything\s+i\s+(?:have|need)\s+to\s+do|"
    r"what(?:'s|\s+is)\s+on\s+my\s+plate"
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
    r"\b(?:generate|create|make|draw|paint|render|illustrate)\s+"
    r"(?:(?:an?\s+|the\s+|this\s+|me\s+(?:an?\s+)?)?"
    r"(?:new\s+|another\s+|second\s+|different\s+|happier\s+|cute\s+)*)?"
    r"(?:image|picture|photo|png|illustration)\b|"
    r"\b(?:draw|paint|illustrate)\s+me\b|"
    r"\ba\s+picture\s+of\b|"
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
    r"(?:[-+*/^x×÷]|times|plus|minus|divided\s+by|over|mod|"
    r"to\s+the\s+power(?:\s+of)?)\s*-?\d"
    r"|(?:what(?:'s|\s+is)|calculate|compute|work\s+out|solve|how\s+much\s+is)\b"
    r"[^?]{0,60}?\b(?:\d+\s*"
    r"(?:[-+*/^x×÷]|times|plus|minus|divided\s+by|percent\s+of)\s*\d"
    r"|square\s+root\b|factorial\b)"
    r")"
)

_LOOK_OR_FILE = re.compile(
    r"(?i)\b("
    r"look at this|"
    r"look at the|"
    r"using the camera|"
    r"with vision|"
    r"ocr this|"
    r"describe (?:the|this|that) (?:image|file|diagram|picture|photo)|"
    r"what(?:'s| is) in (?:this|the|that) (?:image|screenshot|photo|picture|pic)|"
    r"read any text|"
    r"what text|"
    r"text in (?:this|the|that)|"
    r"what in this|"
    r"what's in this|"
    r"summarize (?:the|this|that) file|"
    r"git status|"
    r"what(?:'s| is) on my clipboard|"
    r"generate (?:a |an |me )?(?:simple )?image"
    r")\b"
)

_DESCRIBE_FOLLOWUP = re.compile(
    r"(?i)^\s*(?:please\s+|just\s+)*(?:describe|tell me about)\s+"
    r"(?:it|that|this)\b"
)


def soften_caps(text: str) -> str:
    """Sherpa ALL-CAPS lines still have to parse as normal speech."""
    raw = (text or "").strip()
    letters = [c for c in raw if c.isalpha()]
    if len(letters) < 6:
        return raw
    if (sum(1 for c in letters if c.isupper()) / len(letters)) < 0.8:
        return raw
    return raw[0].upper() + raw[1:].lower()


def looks_like_workspace_write(text: str) -> bool:
    """True when the utterance is about creating/editing a file, not SMS."""
    return bool(_WORKSPACE_WRITE.search(text or ""))


def looks_like_goals_utterance(text: str) -> bool:
    """True when the utterance is about listing/updating goals, not SMS body."""
    return bool(_GOALS_UTTERANCE.search(text or ""))


def looks_like_tasks_utterance(text: str) -> bool:
    """True when the utterance is about to-dos, not an SMS body."""
    raw = text or ""
    return bool(_TASKS_UTTERANCE.search(raw) or _TASKS_DAY_ASK.search(raw))


def looks_like_memory_utterance(text: str) -> bool:
    """True for remember/forget turns that must not revive a pending SMS."""
    return bool(_MEMORY_UTTERANCE.search(text or ""))


def looks_like_contacts_utterance(text: str) -> bool:
    """True for contact-book lookups that must not revive a pending SMS."""
    return bool(_CONTACTS_UTTERANCE.search(text or ""))


def looks_like_contact_email_ask(text: str) -> bool:
    raw = text or ""
    return bool(_CONTACT_EMAIL_ASK.search(raw)) and not bool(re.search(r"(?i)\bphone\b", raw))


def looks_like_contact_phone_ask(text: str) -> bool:
    """True when they asked for a number, not the whole contact card."""
    if looks_like_contact_email_ask(text):
        return False
    return bool(_CONTACT_PHONE_ASK.search(text or ""))


def looks_like_contacts_followup(text: str, history: list[Any] | None = None) -> bool:
    """True for 'proceed' after a contacts lookup that never called the tool."""
    if not _CONTACTS_PROCEED.match((text or "").strip()):
        return False
    for item in reversed(history or []):
        role = getattr(item, "role", None) or (item.get("role") if isinstance(item, dict) else "")
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if str(role) == "user" and looks_like_contacts_utterance(str(content or "")):
            return True
    return False


def looks_like_look_or_file(text: str) -> bool:
    """True for vision / OCR / attach / git / clipboard turns — not an SMS body."""
    return bool(_LOOK_OR_FILE.search(text or ""))


def looks_like_greeting(text: str) -> bool:
    """True for hello / how-are-you — not an SMS body and not a news ask."""
    return bool(_GREETING.match((text or "").strip()))


def looks_like_math_ask(text: str) -> bool:
    """True for arithmetic turns that must not revive or feed an SMS draft."""
    return bool(_MATH_ASK.match(soften_caps((text or "").strip())))


def looks_like_describe_followup(text: str) -> bool:
    """True for 'just describe it' after a failed image — not an SMS body."""
    return bool(_DESCRIBE_FOLLOWUP.match((text or "").strip()))


def looks_like_closing_chitchat(text: str) -> bool:
    """True for short thanks/bye turns that must not revive weather/SMS tools."""
    return bool(_CLOSING_CHITCHAT.match((text or "").strip()))


def looks_like_image_edit(text: str) -> bool:
    """True when the utterance is resize / overlay / adjust, not an SMS body."""
    raw = text or ""
    from arelis.attachments import split_attachments_turn, wants_image_edit

    _block, ask = split_attachments_turn(raw)
    return wants_image_edit(ask or raw)


def looks_like_image_gen(text: str) -> bool:
    """True when the utterance is Comfy/image generate, not an SMS body."""
    raw = text or ""
    from arelis.attachments import (
        split_attachments_turn,
        wants_image_edit,
        wants_image_restyle,
        wants_image_surgical,
        wants_image_variations,
        wants_same_seed,
    )

    _block, ask = split_attachments_turn(raw)
    check = ask or raw
    # Restyle / surgical / variations / same-seed are still Comfy. Pixel edits are not.
    if (
        wants_image_restyle(check)
        or wants_image_surgical(check)
        or wants_image_variations(check)
        or wants_same_seed(check)
    ):
        return True
    if wants_image_edit(check):
        return False
    return bool(_IMAGE_GEN.search(check))


def looks_like_browser_or_url(text: str) -> bool:
    """True for open-site / URL turns that must not revive a pending SMS draft."""
    return bool(_BROWSER_OR_URL.match((text or "").strip()))
