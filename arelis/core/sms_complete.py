"""Fill send_sms (to, body) from the current turn and recent chat.

Small models often split "text Brian" and "say I'm late" across turns, then
re-ask for the body forever. This module reconstructs a draft so preflight and
the agent loop can nudge with concrete args — still never sends without Allow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arelis.contacts import Contact, load_contacts, resolve_contact
from arelis.core.complete_protocol import (
    SEND_ALLOW_CLOSER,
    history_with_current,
    next_unsent,
    remaining_labels,
    unfinished_call_notice,
)
from arelis.core.confirm_patterns import (
    proceed_ask_pattern,
    send_command_pattern,
    send_confirm_pattern,
)
from arelis.core.contact_match import find_contact

# Re-exported, not merely imported. Fourteen modules and the test suite reach
# for these through this module's name, so moving them to `utterance_guards`
# had to keep this door open — the point of the move was to stop *new* callers
# arriving here for a greeting, not to break the ones that already had.
from arelis.core.utterance_guards import (
    looks_like_browser_or_url,
    looks_like_closing_chitchat,
    looks_like_contact_email_ask,
    looks_like_contact_phone_ask,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_describe_followup,
    looks_like_goals_utterance,
    looks_like_greeting,
    looks_like_image_edit,
    looks_like_image_gen,
    looks_like_look_or_file,
    looks_like_math_ask,
    looks_like_memory_utterance,
    looks_like_tasks_utterance,
    looks_like_workspace_write,
    soften_caps,
)
from arelis.history_view import history_pairs

__all__ = [
    "SmsDraft",
    "complete_sms_draft",
    "draft_send_sms_args",
    "fill_send_sms_args",
    "looks_like_browser_or_url",
    "looks_like_closing_chitchat",
    "looks_like_contact_email_ask",
    "looks_like_contact_phone_ask",
    "looks_like_contacts_followup",
    "looks_like_contacts_utterance",
    "looks_like_describe_followup",
    "looks_like_goals_utterance",
    "looks_like_greeting",
    "looks_like_image_edit",
    "looks_like_image_gen",
    "looks_like_look_or_file",
    "looks_like_math_ask",
    "looks_like_memory_utterance",
    "looks_like_phone_number",
    "looks_like_stale_sms_skip",
    "looks_like_tasks_utterance",
    "looks_like_workspace_write",
    "normalize_sms_args",
    "parse_sms_utterance",
    "resolve_sms_alias",
    "sms_force_call_notice",
    "sms_intent_this_turn",
    "sms_preflight_nudge",
]

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
    # Digits first: "text 5551112222 and tell him …" used to miss because
    # `to` required a letter, so send_sms was hidden and the model invented it.
    r"(?P<to>\+?(?:1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]*)\d{3}[\s.\-]*\d{4}"
    r"(?:\s*(?:and|&|,)\s*\+?(?:1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]*)\d{3}[\s.\-]*\d{4}){0,4}"
    r"|(?:my\s+)?[A-Za-z][A-Za-z0-9_.\-]{0,40}"
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

# "text in that last picture" / "text this screenshot" — prepositions, not people.
_SMS_TO_STOPWORDS = frozenset(
    {
        "in",
        "the",
        "this",
        "that",
        "any",
        "a",
        "an",
        "your",
        "last",
        "picture",
        "image",
        "photo",
        "screenshot",
        "file",
        "it",
    }
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

# "tell her I love her" is reported speech. The recipient should read "I love you".
# Possessives stay put: "I love her cooking" is not this pattern.
_ADDRESSEE_OBJECT = re.compile(
    r"(?i)^(?:that\s+)?(?P<head>i|we)\s+(?:just\s+)?"
    r"(?P<verb>love|miss|need|adore)\s+"
    r"(?:her|him|them)"
    r"(?P<tail>(?:\s+(?:so\s+much|very\s+much|too|always|forever|dearly|a\s+lot))?)"
    r"(?P<punct>\s*[.!]*)"
    r"$"
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
        # SymPy / markdown: ```text\napart: … is not "text apart: …".
        "apart",
        "sympy",
        "python",
        # Overlay / layout words: "add text right in the middle that says…"
        "middle",
        "center",
        "centre",
        "picture",
        "image",
        "photo",
        "screenshot",
    }
)

# Fenced listings. ```text\napart: 1+2 is a code dump, not send_sms(to=apart).
_CODE_FENCE = re.compile(r"```[\w.+-]*\r?\n[\s\S]*?(?:```|$)")

_EXPLICIT_SMS_VERB = re.compile(
    r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message)|"
    r"senatic'?s?|semantic'?s?|message\s+to)\b"
)

# Buried under chitchat: "chillin, i want you to text 555…"
_WANT_YOU_TO_TEXT = re.compile(
    r"(?i)\b(?:i\s+want\s+you\s+to|can\s+you|could\s+you|please)\s+"
    r"(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b"
)

_TEXT_A_NUMBER = re.compile(
    r"(?i)\b(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\s+"
    r"(?:to\s+)?\+?(?:1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]*)\d{3}[\s.\-]*\d{4}\b"
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
_SEND_VERBS = (
    r"send\s+(?:the\s+)?(?:text|sms|message|it|that)",
    r"send\s+it\s+(?:now|please)",
    r"please\s+send(?:\s+it)?",
)
_SEND_CONFIRM = send_confirm_pattern(*_SEND_VERBS, affirmations=("please",))
# The half that stands on its own. See `core.confirm_patterns`.
_SEND_COMMAND = send_command_pattern(*_SEND_VERBS)

# Bare "confirm" is on this list and on no other. The Allow card says Confirm,
# so on the send channels the word is as likely to be the user reading the
# button back as it is a new offer — and treating it as an offer is what lets
# the next "yes" mean send.
_PROCEED_ASK = proceed_ask_pattern("send", "sending", r"confirm(?:ation)?")


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
        """Ready to send when body is set and every recipient has an address.

        An address is a book alias *or* a number they typed. Missing names
        are not a gate — they mean ask for the number, not 'add them first'.
        """
        if not self.body.strip():
            return False
        names = self.all_tos
        if not names:
            return False
        if self.missing:
            return False
        if len(names) == 1:
            return True
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


def looks_like_phone_number(value: str) -> bool:
    """True for a number someone would actually dial, not a short code or '2'."""
    from arelis.contacts import normalize_phone, to_e164

    raw = (value or "").strip()
    if not raw:
        return False
    return bool(to_e164(raw) and len(normalize_phone(raw)) >= 10)


def _clean_to(raw: str) -> str:
    return (raw or "").strip().rstrip(".,!;:")


def _address_the_recipient(text: str) -> str:
    """Flip a bound third-person object so the text reads as to them."""
    match = _ADDRESSEE_OBJECT.match((text or "").strip())
    if not match:
        return text
    return (
        f"{match.group('head')} {match.group('verb')} you"
        f"{match.group('tail')}{match.group('punct')}"
    )


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
    return _address_the_recipient(text)


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


def resolve_sms_alias(to: str, contacts: dict[str, Contact] | None = None) -> str:
    """Map a spoken name to a contacts.yaml alias when possible.

    The lookup itself moved to `core.contact_match`, because email was asking
    the same question with a weaker version of it and mailing the wrong person
    on a surname typo. What is left here is the SMS projection: the tool wants
    the book alias, not the number, so the number stays in one place.

    `load_contacts` is read off this module deliberately — the SMS tests
    monkeypatch it here, so the default must resolve through this namespace
    rather than the shared module's.
    """
    book = contacts if contacts is not None else load_contacts()
    hit = find_contact(to, book)
    return hit.alias if hit is not None else ""


def _bind_recipients(
    names: list[str], book: dict[str, Contact]
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return (primary_to, primary_alias, recipients, aliases, missing)."""
    if not names:
        return "", "", (), (), ()
    aliases: list[str] = []
    missing: list[str] = []
    for name in names:
        if looks_like_phone_number(name):
            aliases.append(name)
            continue
        alias = resolve_sms_alias(name, book)
        aliases.append(alias)
        if not alias:
            missing.append(name)
    primary = names[0]
    return primary, aliases[0], tuple(names), tuple(aliases), tuple(missing)


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
    if _WANT_YOU_TO_TEXT.search(raw) or _TEXT_A_NUMBER.search(raw):
        return True
    return parse_sms_utterance(raw) is not None


def looks_like_stale_sms_skip(text: str, history: list[Any] | None = None) -> bool:
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
        or looks_like_image_edit(text)
        or looks_like_describe_followup(text)
        or looks_like_browser_or_url(text)
        or looks_like_look_or_file(text)
    )


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


def _strip_code_fences(text: str) -> str:
    """Drop markdown fences so language tags cannot parse as an SMS verb."""
    return _CODE_FENCE.sub(" ", text or "")


def parse_sms_utterance(text: str) -> SmsDraft | None:
    """Parse a single user utterance into an SMS draft (maybe incomplete)."""
    raw = soften_caps((text or "").strip())
    raw = _strip_code_fences(raw).strip()
    if not raw:
        return None
    # OCR / "read any text in that last picture" is never a send, even when
    # the word "text" sits next to a preposition the send regex treats as `to`.
    if looks_like_look_or_file(raw):
        return None
    # File-write phrasing that happens to contain "text" must not become SMS.
    if looks_like_workspace_write(raw) and not _EXPLICIT_SMS_VERB.match(raw):
        return None
    # Overlay / resize: "add text right in the middle that says Arelis".
    if looks_like_image_edit(raw) and not _EXPLICIT_SMS_VERB.match(raw):
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
    # "text in that picture" parsed to="in". Those are never people.
    if primary.lower() in _SMS_TO_STOPWORDS:
        return None
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

    # Include the current user text as the newest user turn for merging.
    # (AgentLoop adds the user message before we read history, so it may already
    # be the last entry — dedupe by comparing content.)
    pairs = history_with_current(history, user_text)

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
        # This walk is stricter than the shared one in `core.history_revival`:
        # it stops on any non-offer turn, and it has two exits the shared walk
        # does not model (a recipient-only draft below, and the bare-number
        # address fill after it). It stays hand-written on purpose — four
        # callbacks and a sentinel value is not an improvement in the function
        # that decides what text messages get sent.
        #
        # `granted` is the other direction of the mistake email made. An
        # explicit "send the text" is its own grant and does not need the
        # assistant to have offered: when the model stalled with "Ready when
        # you are." instead of asking, this branch refused every time and
        # never said why.
        #
        # It deliberately does not seed `saw_ask`, which would have been the
        # one-line version. `saw_ask` also licenses walking *past* a user turn
        # this module cannot parse, and a command must not buy that. "Never
        # mind, what is the weather" ends the draft; a later "send the text"
        # is then about nothing, and reviving across it would be reviving
        # something the user cancelled.
        granted = bool(_SEND_COMMAND.match(user_text or ""))
        saw_ask = False
        for role, content in reversed(pairs[:-1]):
            if role == "assistant":
                if _ASKED_FOR_BODY.search(content or "") or _PROCEED_ASK.search(content or ""):
                    saw_ask = True
                elif not (saw_ask or granted):
                    break
                continue
            if role == "user":
                prior = parse_sms_utterance(content)
                if prior and prior.all_tos and prior.body:
                    # Bare "yes" after a non-SMS turn must not revive an older
                    # complete draft — only confirm when the assistant just
                    # asked about sending.
                    if saw_ask or granted:
                        return _finalize_draft(
                            names=list(prior.all_tos),
                            body=prior.body,
                            source="history",
                            book=book,
                        )
                    break
                if prior and prior.all_tos and not prior.body and (saw_ask or granted):
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

    # A bare number after "text Alex …" fills the address. Contacts stay optional.
    if current is None and looks_like_phone_number(user_text):
        number = user_text.strip()
        for role, content in reversed(pairs[:-1]):
            if role != "user":
                continue
            prior = parse_sms_utterance(content)
            if prior and prior.all_tos and prior.body:
                prior_done = _finalize_draft(
                    names=list(prior.all_tos),
                    body=prior.body,
                    source="history",
                    book=book,
                )
                if prior_done.missing:
                    names = [
                        number if name in prior_done.missing else name
                        for name in prior_done.all_tos
                    ]
                    return _finalize_draft(
                        names=names,
                        body=prior.body,
                        source="history",
                        book=book,
                    )
            break

    # Case B: current text is NOT an SMS verb — treat as body after a pending ask.
    if current is None and user_text.strip() and not _SMS_VERB.match(user_text):
        if _SEND_CONFIRM.match(user_text or ""):
            return None
        if looks_like_phone_number(user_text):
            return None
        # Goals / tasks / memory / contacts / file-write / image-gen /
        # calendar / open-URL / analyze turns must not steal a pending SMS.
        from arelis.core.other_work import looks_like_other_work, looks_like_sent_compose

        if looks_like_other_work(user_text, history):
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
            if role == "assistant":
                if looks_like_sent_compose(content or ""):
                    return None
                if _ASKED_FOR_BODY.search(content or ""):
                    saw_ask = True
                continue
            if role == "user":
                prior = parse_sms_utterance(content)
                if prior and prior.all_tos and not prior.body:
                    if saw_ask:
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

    Whenever the draft carries a body, that body is locked — the model cannot
    overwrite it with a different invent. Confirm cards therefore show the body
    that will actually send. For multi-recipient drafts, `to` is the next
    unresolved alias not already sent this turn.
    """
    out = normalize_sms_args(args if draft is None else dict(args))
    if draft is None:
        return out
    sent = {s.lower() for s in (already_sent or set())}
    candidates = draft.resolved_aliases or ((draft.tool_to,) if draft.tool_to else ())
    next_to = next_unsent(candidates, already_sent, draft.tool_to)

    # A draft body is always the user's own words, whether it came from this
    # turn or the one that opened the thread. Whether the recipient resolves to
    # a book entry is a separate question, so an unknown name is no licence for
    # the model to rewrite the message.
    if draft.body:
        from arelis.core.turn_goal import sms_body_serves_goal

        if sms_body_serves_goal(draft.body):
            out["body"] = draft.body

    if draft.complete:
        if next_to:
            # Preserve a model `to` that is still one of the intended recipients.
            model_to = str(out.get("to") or "").strip()
            if model_to:
                # Multi-token "robin, wife" already peeled in normalize.
                model_alias = resolve_sms_alias(model_to, contacts) or model_to
                if (
                    model_alias.lower() in {a.lower() for a in draft.resolved_aliases}
                    and model_alias.lower() not in sent
                ):
                    out["to"] = model_alias
                else:
                    out["to"] = next_to
            else:
                out["to"] = next_to
        return out
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
    if draft.missing:
        miss = ", ".join(draft.missing)
        return (
            "Intent preflight: the user wants to text "
            f"{miss}, but there is no number yet. Ask for the number, then "
            "call send_sms with that number and the body they already gave. "
            "Contacts are a nickname hint, not a gate — do not require "
            "contacts(action=add) before sending. Do not invent a number."
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
    if draft.missing:
        miss = ", ".join(draft.missing)
        return (
            f"Do not send yet — need a number for: {miss}. "
            "Ask for it, then call send_sms. Do not invent a number. "
            "Saving them in contacts is optional."
        )
    remaining = remaining_labels(draft.resolved_aliases, already_sent)
    target = remaining[0] if remaining else draft.tool_to
    extra = ""
    if len(remaining) > 1:
        extra = f" Then repeat for: {', '.join(remaining[1:])}."
    return unfinished_call_notice(
        "send_sms",
        f'Call it now with to="{target}" body="{draft.body[:300]}"',
        extra=extra,
        after=SEND_ALLOW_CLOSER,
    )
