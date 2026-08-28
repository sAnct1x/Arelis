"""Fill send_email (to, subject, body) from the current turn and recent chat.

Small models often split "email Brian about dinner" and the body across turns,
then invent a different subject on the confirm card. This module reconstructs a
draft so preflight and the agent loop can nudge with concrete args — still never
sends without Allow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arelis.contacts import Contact, load_contacts, match_contact_label, resolve_contact
from arelis.history_view import history_pairs
from arelis.mail import valid_address

# Verb + recipient only. Subject/body are split in parse_email_utterance so
# a bare "re" alternative cannot steal letters from "Dinner" / "Thursday".
_EMAIL_SEND = re.compile(
    r"(?i)\b(?:"
    r"e-?mail|send\s+(?:an?\s+)?(?:e-?mail|mail)|compose\s+(?:an?\s+)?(?:e-?mail|mail)"
    r")\s+"
    r"(?:to\s+)?"
    r"(?P<to>(?:my\s+)?(?:[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}|"
    r"[A-Za-z][A-Za-z0-9_.\-]{0,40}"
    r"(?:\s+(?!that\b|saying\b|about\b|subject\b|re\b|body\b)"
    r"[A-Za-z][A-Za-z0-9_.\-]{0,40}){0,3}))"
    r"(?P<rest>.*)$"
)

# "email a file to addr" / "email that image to addr" / "email the attached file to addr"
_EMAIL_FILE_TO = re.compile(
    r"(?i)\b(?:e-?mail|send)\s+(?:(?:an?\s+|the\s+|this\s+|that\s+)?"
    r"(?:attached\s+)?"
    r"(?:file|pdf|document|attachment|it|image|photo|picture|png)\s+)?"
    r"(?:to\s+)?(?P<to>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
)

# Image/photo only — never use this to attach a random generated PNG to an
# "email this document / xlsx" turn.
_IMAGE_ATTACH_CUE = re.compile(
    r"(?i)\b(?:that|the|this|an?)\s+(?:image|photo|picture|png)\b|"
    r"\b(?:e-?mail|send)\s+(?:that|the|this)\s+(?:image|photo|picture)\b"
)

_MEDIA_ATTACH_CUE = re.compile(
    r"(?i)\b(?:that|the|this|an?)\s+(?:image|photo|picture|png|file|attachment|document)\b|"
    r"\b(?:attach|attached|attachment)\b|"
    r"\b(?:e-?mail|send)\s+it\s+to\b|"
    r"\b(?:e-?mail|send)\s+(?:the\s+)?(?:attached\s+)?(?:file|document)\b|"
    r"\b(?:file|pdf|document)\b"
)

_WITH_SUBJECT = re.compile(
    r"(?i)\b(?:with\s+)?subject\s*[:=]?\s*(?P<subject>.+)$"
)
# The curly quotes are the point, not a typo: Windows autocorrect and phone
# keyboards produce them, and a user who typed a smart quote must still get their
# subject parsed. RUF001 flags them as ambiguous, which is exactly why they are
# listed explicitly alongside the straight forms.
_QUOTED_SUBJECT_BODY = re.compile(
    r"(?i)\b(?:with\s+)?subject\s*[:=]?\s*[\"'“”‘’](?P<subject>[^\"'“”‘’]+)[\"'“”‘’]"
    r"(?:\s*,)?(?:\s+and)?\s+body\s*[:=]?\s*[\"'“”‘’](?P<body>[^\"'“”‘’]+)[\"'“”‘’]"
)

_FILE_PATH = re.compile(
    r"(?P<path>"
    r'"[^"\n]+\.[A-Za-z0-9]{1,8}"|'
    r"'[^'\n]+\.[A-Za-z0-9]{1,8}'|"
    r"[A-Za-z]:\\[^\s\"']+|"
    r"/(?:[^\s\"']+/)*[^\s\"']+\.[A-Za-z0-9]{1,8}|"
    r"data/drops/[^\s\"']+|"
    r"(?:[\w.\- ()\[\]]+/)*[\w.\- ()\[\]]+\."
    r"(?:xlsx|xls|csv|tsv|tab|pdf|png|jpe?g|webp|gif|docx?|txt|md|zip)\b"
    r")"
)

# "email this document to …" / "email the attached file to …"
_COMPOSE_EMAIL_SHAPE = re.compile(
    r"(?i)\b("
    r"e-?mail|send\s+(?:an?\s+)?(?:e-?mail|mail)|compose\s+(?:an?\s+)?(?:e-?mail|mail)"
    r")\b"
)

# Recurring / "at 7am every day" is a Windows job, not a send this turn.
# Intensifiers are a closed list so "every time it rains" stays a weather ask.
_SCHEDULED_SEND = re.compile(
    r"(?i)\b("
    r"every\s+(?:single\s+|last\s+|other\s+)?(?:day|morning|evening|night|weekday)|"
    r"each\s+day|"
    r"once\s+a\s+day|"
    r"daily\s+at|"
    r"schedule\s+a\s+(?:job|briefing|task)|"
    r"recurring"
    r")\b"
)
_SCHEDULED_SEND_PAYLOAD = re.compile(
    r"(?i)\b(e-?mail|mail|text|sms|briefing|weather|summary|digest)\b"
)
_STANDARD_BRIEFING = re.compile(
    r"(?i)\b("
    r"morning\s+briefing|"
    r"morning\s+summary|"
    r"what'?s\s+going\s+on\s+today|"
    r"create_briefing"
    r")\b"
)
_CUSTOM_JOB_TONE = re.compile(
    r"(?i)\b(fun|friendly|witty|jok(?:e|y)|keep\s+it\s+brief)\b"
)
_SCHEDULE_MANAGE = re.compile(
    r"(?i)\b(?:"
    r"(?:show|list|see|delete|remove|cancel|stop|disable|"
    r"what(?:'s|s|\s+are)?|which)\b"
    r".{0,80}\b(?:briefings?|automations?|scheduled\s+jobs?|"
    r"(?:my|the)\s+jobs?)"
    r"|"
    r"(?:briefings?|automations?|scheduled\s+jobs?)\b.{0,40}\b"
    r"(?:do\s+i\s+have|have\s+i|are\s+there)"
    r")"
)

_MAILBOX_MUTATE = re.compile(
    r"(?i)\b(?:delete|trash|archive|remove)\s+"
    r"(?:the\s+|that\s+|this\s+)?"
    r"(?:e-?mail|mail|message)\b"
)

_EMAIL_SEND_FOLLOWUP = re.compile(
    r"(?i)\b("
    r"you have my e-?mail|"
    r"(?:use|failed to use)\s+the correct tool|"
    r"(?:e-?mail|send)\s+(?:it|the\s+(?:pdf|file|document)|that)\s+to|"
    r"e-?mail the pdf|"
    r"send the pdf"
    r")\b"
)


def looks_like_scheduled_send(text: str) -> bool:
    """True when they asked to mail/text later on a timer, not send now."""
    raw = text or ""
    if not _SCHEDULED_SEND.search(raw):
        return False
    if _SCHEDULED_SEND_PAYLOAD.search(raw):
        return True
    return bool(re.search(r"(?i)\bschedule\s+a\s+(?:job|briefing|task)\b", raw))


def looks_like_schedule_manage(text: str) -> bool:
    """True when they asked to list, inspect, or delete a saved job.

    Nouns in a job title ('Morning Weather Briefing') are not this-turn
    weather or mail. A create-timer ask is scheduled_send, not manage.
    """
    raw = text or ""
    if looks_like_scheduled_send(raw):
        return False
    return bool(_SCHEDULE_MANAGE.search(raw))


def looks_like_mailbox_mutate(text: str) -> bool:
    """True for delete/trash/archive that email — inbox, not send_email."""
    return bool(_MAILBOX_MUTATE.search(text or ""))


def _history_had_email_send(history: list[Any] | None) -> bool:
    if not history:
        return False
    for item in history[-8:]:
        if isinstance(item, dict):
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
        else:
            role = str(getattr(item, "role", "") or "")
            content = str(getattr(item, "content", "") or "")
        blob = f"{role} {content}".lower()
        if "send_email" in blob or looks_like_compose_email(content):
            return True
    return False


def looks_like_email_send_followup(
    text: str, history: list[Any] | None = None
) -> bool:
    """True when this turn is still a send, even after a summarize drop."""
    raw = text or ""
    if looks_like_mailbox_mutate(raw):
        return False
    if looks_like_compose_email(raw) or named_address_in_text(raw):
        return True
    if _EMAIL_SEND_FOLLOWUP.search(raw) and _history_had_email_send(history):
        return True
    return False


def looks_like_standard_briefing(text: str) -> bool:
    """True for the canned morning digest, not a custom standing prompt.

    create_briefing emails home weather plus mail and open loops. Named extra
    cities, a tone, or any other recurring task is schedule(action=create).
    """
    raw = text or ""
    if _STANDARD_BRIEFING.search(raw):
        return True
    if not looks_like_scheduled_send(raw):
        return False
    from arelis.tools.weather import extract_weather_places

    extra = [p for p in extract_weather_places(raw) if p]
    if extra:
        return False
    if _CUSTOM_JOB_TONE.search(raw):
        return False
    return bool(re.search(r"(?i)\bweather\b", raw))


_BARE_CONFIRM = re.compile(
    r"(?i)^\s*(confirm|yes|yeah|yep|ok|okay|do it|please do|go ahead)\.?\s*$"
)
_SCHEDULE_TIME = re.compile(
    r"(?i)\b(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))\b"
)


def looks_like_bare_confirm(text: str) -> bool:
    """A one-word 'confirm' after Allow already created the job — not run_now."""
    return bool(_BARE_CONFIRM.match(text or ""))


def draft_schedule_briefing_args(text: str) -> dict[str, str]:
    """schedule(action=create_briefing) from 'every day at 7am, email me weather'."""
    raw = text or ""
    time_s = "7am"
    match = _SCHEDULE_TIME.search(raw)
    if match:
        time_s = re.sub(r"\s+", "", match.group(1))
    name = "Morning briefing"
    if re.search(r"(?i)\bweather\b", raw):
        name = "Daily Weather Summary"
    days = "daily"
    if re.search(r"(?i)\bweekday", raw):
        days = "weekdays"
    return {
        "action": "create_briefing",
        "time": time_s,
        "days": days,
        "name": name,
    }


def draft_schedule_job_args(text: str) -> dict[str, str]:
    """schedule(action=create) with the user's standing instruction as the prompt."""
    raw = " ".join((text or "").split()).strip()
    time_s = "7am"
    match = _SCHEDULE_TIME.search(raw)
    if match:
        time_s = re.sub(r"\s+", "", match.group(1))
    days = "daily"
    if re.search(r"(?i)\bweekday", raw):
        days = "weekdays"
    name = raw[:40].strip() or "Scheduled job"
    args: dict[str, str] = {
        "action": "create",
        "name": name,
        "prompt": raw,
        "time": time_s,
        "days": days,
    }
    to = named_address_in_text(raw)
    if to:
        args["recipient"] = to
    return args


def rewrite_schedule_calls(
    text: str,
    calls: list[tuple[str, dict[str, Any]]],
    *,
    schedule_used: bool,
    schedule_available: bool,
) -> list[tuple[str, dict[str, Any]]]:
    """Force create_briefing for a timer ask; never treat 'confirm' as run_now."""
    if looks_like_bare_confirm(text):
        return [
            (name, args)
            for name, args in calls
            if not (
                name == "schedule"
                and str((args or {}).get("action") or "").lower() == "run_now"
            )
        ]
    if not looks_like_scheduled_send(text) or not schedule_available:
        return calls
    drafted = (
        draft_schedule_briefing_args(text)
        if looks_like_standard_briefing(text)
        else draft_schedule_job_args(text)
    )
    out: list[tuple[str, dict[str, Any]]] = []
    saw_schedule = False
    for name, args in calls:
        if name in {"weather", "send_email", "send_sms"}:
            continue
        if name != "schedule":
            out.append((name, args))
            continue
        saw_schedule = True
        action = str((args or {}).get("action") or "").lower()
        if action == "run_now":
            continue
        if action in {"create", "create_briefing", ""}:
            merged = dict(drafted)
            given = str((args or {}).get("name") or "").strip()
            if given:
                merged["name"] = given
            given_prompt = str((args or {}).get("prompt") or "").strip()
            if given_prompt and str(merged.get("action") or "") == "create":
                merged["prompt"] = given_prompt
            given_to = str((args or {}).get("recipient") or "").strip()
            if given_to:
                merged["recipient"] = given_to
            out.append(("schedule", merged))
        else:
            out.append((name, args))
    if not saw_schedule and not schedule_used:
        out.append(("schedule", drafted))
    return out


_ABOUT_SUBJECT = re.compile(
    r"(?i)^\s+(?:about|subject|\bre)\s*:?\s*(?P<rest>.+)$"
)
_BODY_ONLY = re.compile(
    r"(?i)^\s*(?::|that|saying|,)\s*(?P<body>.+)$"
)

_SUBJECT_BODY_LINE = re.compile(
    r"(?i)^(?:subject\s*[:=]\s*(?P<subject>.+?)\s+)?"
    r"(?:body\s*[:=]\s*(?P<body>.+))$"
)

_SKIP_TO = frozenset(
    {
        "him",
        "her",
        "them",
        "someone",
        "back",
        "again",
        "later",
        "the",
        "that",
        "this",
        "image",
        "photo",
        "picture",
        "file",
        "pdf",
        "document",
        "attachment",
    }
)

_SELF_TO = frozenset({"me", "myself"})

_ASKED_FOR_FIELDS = re.compile(
    r"(?i)\b("
    r"what\s+(should|do)\s+(i|you)\s+(say|write|send)|"
    r"what('s| is)\s+the\s+(subject|body|message)|"
    r"what\s+should\s+(the\s+)?(subject|body)|"
    r"who\s+(should|do)\s+i\s+(email|send\s+(?:it\s+)?to)|"
    r"what\s+do\s+you\s+want\s+(it|me)\s+to\s+say|"
    r"tell\s+me\s+what\s+to\s+(say|write)|"
    r"need\s+(a|the)\s+(subject|body)"
    r")\b"
)

_EMAIL_VERB = re.compile(
    r"(?i)(?:^|[\n.!?]\s*)(?:please\s+)?("
    r"e-?mail|send\s+(?:an?\s+)?(?:e-?mail|mail)|"
    r"compose\s+(?:an?\s+)?(?:e-?mail|mail)"
    r")\b"
)

# Revive a prior complete draft when the user just confirms send (R4 / S10).
_SEND_CONFIRM = re.compile(
    r"(?i)^\s*("
    r"send\s+(?:the\s+)?(?:e-?mail|mail|it|that)|"
    r"send\s+it\s+(?:now|please)?|"
    r"(?:yes|yep|yeah|ok|okay|go\s+ahead|do\s+it|ship\s+it)"
    r"(?:\s+please)?|"
    r"please\s+send(?:\s+it)?"
    r")\s*[.!]?\s*$"
)


@dataclass(frozen=True)
class EmailDraft:
    to: str
    subject: str
    body: str
    resolved_to: str = ""
    source: str = "current"
    attach_path: str = ""

    @property
    def unresolved_named_to(self) -> bool:
        """True when a named recipient has no contacts email / literal address."""
        raw = self.to.strip()
        if not raw or raw.lower() in _SELF_TO:
            return False
        if self.resolved_to or valid_address(raw):
            return False
        return True

    @property
    def complete(self) -> bool:
        """Ready to force/send: body set, recipient resolvable (or self).

        Subject may be empty — fill/force defaults it so a missing subject alone
        does not skip the Allow card on the first ask. An attachment alone with
        a short body is also enough.
        """
        if not self.body.strip() and not self.attach_path.strip():
            return False
        if self.unresolved_named_to:
            return False
        return True

    @property
    def tool_to(self) -> str:
        """Preferred `to` arg for send_email (address when known; empty = self)."""
        if self.resolved_to:
            return self.resolved_to
        raw = self.to.strip()
        if not raw or raw.lower() in _SELF_TO:
            return _self_email()
        raw = repair_email_address(raw)
        if valid_address(raw):
            return raw
        # Unresolved names must not reach send_email as a fake address.
        return ""

    @property
    def tool_subject(self) -> str:
        if self.subject.strip():
            return self.subject.strip()
        if self.attach_path.strip():
            from pathlib import Path

            return Path(self.attach_path).name or "A message from Arelis"
        return "A message from Arelis"

    @property
    def tool_body(self) -> str:
        if self.body.strip():
            return self.body.strip()
        if self.attach_path.strip():
            from pathlib import Path

            name = Path(self.attach_path).name
            return f"Please see the attached file ({name})."
        return ""


def _clean_to(raw: str) -> str:
    return (raw or "").strip().rstrip(".,!;:")


_BARE_MAIL_TLD = {
    "gmail": "gmail.com",
    "yahoo": "yahoo.com",
    "hotmail": "hotmail.com",
    "outlook": "outlook.com",
    "icloud": "icloud.com",
    "aol": "aol.com",
}
_BARE_MAIL = re.compile(
    r"(?i)\b(?P<user>[A-Za-z0-9._%+\-]+)@(?P<prov>"
    + "|".join(_BARE_MAIL_TLD)
    + r")\b(?!\.)"
)


def repair_email_address(raw: str) -> str:
    """Turn you@gmail into you@gmail.com. Leave complete addresses alone."""
    text = _clean_to(raw)
    if valid_address(text):
        return text
    hit = _BARE_MAIL.search(text) or _BARE_MAIL.search(raw or "")
    if not hit:
        return text
    fixed = f"{hit.group('user')}@{_BARE_MAIL_TLD[hit.group('prov').lower()]}"
    return fixed if valid_address(fixed) else text


def named_address_in_text(text: str) -> str:
    """First usable mailbox in free text, including bare @gmail / @yahoo."""
    raw = text or ""
    m = re.search(
        r"(?i)\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
        raw,
    )
    if m and valid_address(m.group(1)):
        return _clean_to(m.group(1))
    return repair_email_address(_BARE_MAIL.search(raw).group(0)) if _BARE_MAIL.search(raw) else ""


def _clean_text(raw: str) -> str:
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _self_email() -> str:
    """The user's inbox for me/myself/empty — never Arelis's SMTP from-address."""
    from arelis.mail import owner_inbox

    return owner_inbox()


def resolve_email_address(
    to: str, contacts: dict[str, Contact] | None = None
) -> str:
    """Map a spoken name or address to a usable send_email `to` value."""
    raw = _clean_to(to)
    if not raw or raw.lower() in _SELF_TO:
        return _self_email()
    raw = repair_email_address(raw)
    if valid_address(raw):
        return raw
    book = contacts if contacts is not None else load_contacts()
    hit = resolve_contact(raw, book)
    if hit is not None and hit.email:
        return hit.email
    labeled = match_contact_label(raw, book)
    if labeled is not None and labeled.email:
        return labeled.email
    first = raw.split()[0].lower() if raw else ""
    if first and len(first) >= 2:
        for contact in book.values():
            if not contact.email:
                continue
            if first in contact.keys:
                return contact.email
            name_first = (contact.name or "").split()[0].lower()
            if name_first and name_first == first:
                return contact.email
    return ""


def _extract_file_path(text: str) -> str:
    m = _FILE_PATH.search(text or "")
    if not m:
        return ""
    path = (m.group("path") or "").strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in {"'", '"'}:
        path = path[1:-1].strip()
    return path


def _looks_like_analyze_file_ask(text: str) -> bool:
    """Summarize/analyze a local table or JSON — not compose, unless they said email."""
    raw = text or ""
    if _EMAIL_VERB.search(raw):
        return False
    if not re.search(r"(?i)\b(summarize|analyse|analyze|describe)\b", raw):
        return False
    return bool(
        re.search(r"(?i)\b(csv|xlsx|tsv|spreadsheet|json|table)\b", raw)
    )


def looks_like_compose_email(text: str) -> bool:
    """True when the user is asking to send/compose mail (not analyze a table)."""
    raw = (text or "").strip()
    if not raw:
        return False
    if not _COMPOSE_EMAIL_SHAPE.search(raw):
        return False
    if _looks_like_analyze_file_ask(raw):
        return False
    # Inbox triage ("check my email") is not compose.
    if re.search(
        r"(?i)\b("
        r"check\s+(?:my\s+)?(?:e-?mail|mail|inbox)|"
        r"what(?:'s|\s+is)\s+in\s+my\s+(?:inbox|mail|e-?mail)|"
        r"summarize\s+(?:my\s+)?(?:inbox|mail|e-?mail)|"
        r"unread\s+(?:mail|e-?mail|messages?)"
        r")\b",
        raw,
    ) and not re.search(
        r"(?i)\b(?:send|compose|forward|reply\s+to)\b",
        raw,
    ):
        return False
    if valid_address_in_text(raw):
        return True
    if _MEDIA_ATTACH_CUE.search(raw) or _extract_file_path(raw):
        return True
    if re.search(r"(?i)\b(?:to\s+(?:my\s+)?\w+|about\b)", raw):
        return True
    return bool(_EMAIL_VERB.search(raw))


def valid_address_in_text(text: str) -> bool:
    m = re.search(
        r"(?i)\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
        text or "",
    )
    return bool(m and valid_address(m.group(1)))


def resolve_attach_path(raw: str) -> str:
    """Turn a user/model attach string into an existing filesystem path, or ''."""
    from pathlib import Path

    from arelis.paths import state_dir, user_data_dir

    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    root = user_data_dir()
    candidates: list[Path] = [Path(text)]
    # Staged drops often show up as data/drops/… or a leading /drops/…
    cleaned = text.lstrip("/").replace("\\", "/")
    if cleaned.startswith("drops/"):
        cleaned = "data/" + cleaned
    if cleaned.startswith("data/drops/"):
        candidates.append(root / cleaned)
    candidates.append(root / text)
    candidates.append(root / cleaned)
    for cand in candidates:
        try:
            resolved = cand.expanduser()
            if resolved.is_file():
                return str(resolved.resolve())
        except OSError:
            continue

    # Bare filename: prefer Downloads, then newest staged drop with that name.
    name = Path(text).name
    if name and ("/" not in text.replace("\\", "/").rstrip(name) or text == name):
        for folder in (Path.home() / "Downloads", state_dir() / "drops"):
            try:
                if not folder.exists():
                    continue
                if folder.name.lower() == "downloads":
                    hit = folder / name
                    if hit.is_file():
                        return str(hit.resolve())
                else:
                    matches = sorted(
                        folder.rglob(name),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    for hit in matches:
                        if hit.is_file():
                            return str(hit.resolve())
            except OSError:
                continue
    return ""


def parse_email_utterance(text: str) -> EmailDraft | None:
    """Parse a single user utterance into an email draft (maybe incomplete)."""
    raw = (text or "").strip()
    if not raw:
        return None
    if looks_like_scheduled_send(raw):
        return None
    attach = _extract_file_path(raw)

    # Prefer literal "email … to user@host" when a file/path/media cue is present —
    # otherwise fall through to the normal compose parser.
    file_to = _EMAIL_FILE_TO.search(raw)
    if file_to and valid_address(file_to.group("to") or ""):
        has_file_cue = bool(attach) or bool(_MEDIA_ATTACH_CUE.search(raw))
        if has_file_cue:
            to_addr = _clean_to(file_to.group("to") or "")
            body = ""
            subject = ""
            subj_m = _WITH_SUBJECT.search(raw)
            if subj_m:
                subject = _clean_text(subj_m.group("subject") or "")
            if attach:
                from pathlib import Path

                body = f"Please see the attached file ({Path(attach).name})."
            elif _MEDIA_ATTACH_CUE.search(raw):
                body = "Please see the attached file."
            return EmailDraft(
                to=to_addr,
                subject=subject,
                body=body,
                source="current",
                attach_path=attach,
            )

    match = _EMAIL_SEND.search(raw)
    if not match:
        named = named_address_in_text(raw)
        if named and (
            _EMAIL_VERB.search(raw)
            or _EMAIL_SEND_FOLLOWUP.search(raw)
            or _MEDIA_ATTACH_CUE.search(raw)
        ):
            to = named
        else:
            return None
    else:
        to = _clean_to(match.group("to") or "")
    named = named_address_in_text(raw)
    if named:
        to = named
    first = to.split()[0].lower() if to else ""
    if not to or first in _SKIP_TO:
        # "Email that image to addr…" without a media match above — recover the
        # literal address so we do not invent a name-shaped recipient.
        addr_m = re.search(
            r"(?i)\b(?P<to>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
            raw,
        )
        if addr_m and valid_address(addr_m.group("to") or "") and _EMAIL_VERB.search(
            raw
        ):
            to_addr = _clean_to(addr_m.group("to") or "")
            subject = ""
            body = ""
            quoted_early = _QUOTED_SUBJECT_BODY.search(raw)
            if quoted_early:
                return EmailDraft(
                    to=to_addr,
                    subject=_clean_text(quoted_early.group("subject") or ""),
                    body=_clean_text(quoted_early.group("body") or ""),
                    source="current",
                    attach_path=attach,
                )
            subj_m = _WITH_SUBJECT.search(raw)
            if subj_m:
                subject = _clean_text(subj_m.group("subject") or "")
            else:
                after = raw[addr_m.end() :]
                body_only = _BODY_ONLY.match(after)
                if body_only:
                    body = _clean_text(body_only.group("body") or "")
            if attach and not body:
                from pathlib import Path

                body = f"Please see the attached file ({Path(attach).name})."
            elif _MEDIA_ATTACH_CUE.search(raw) and not body:
                body = "Please see the attached file."
            return EmailDraft(
                to=to_addr,
                subject=subject,
                body=body,
                source="current",
                attach_path=attach,
            )
        return None
    # "email a file …" — "a" / "file" must not become the recipient.
    if first in {"a", "an", "the", "file", "pdf", "document", "attachment"}:
        return None
    if first in _SELF_TO and not named:
        to = "me"
    rest = (match.group("rest") if match else "") or ""
    if not rest and named:
        after = raw.split(named, 1)
        rest = after[1] if len(after) > 1 else ""
    subject = ""
    body = ""
    quoted = _QUOTED_SUBJECT_BODY.search(raw)
    if quoted:
        subject = _clean_text(quoted.group("subject") or "")
        body = _clean_text(quoted.group("body") or "")
        if attach and not body:
            from pathlib import Path

            body = f"Please see the attached file ({Path(attach).name})."
        return EmailDraft(
            to=to,
            subject=subject,
            body=body,
            source="current",
            attach_path=attach,
        )
    # "subject: test, body: hello" — must not treat "body:" as subject colon.
    inline = re.match(
        r"(?i)^\s*subject\s*[:=]\s*(?P<subject>.+?)\s*,?\s+"
        r"body\s*[:=]\s*(?P<body>.+)$",
        rest,
    )
    if inline:
        subject = _clean_text(inline.group("subject") or "")
        body = _clean_text(inline.group("body") or "")
    else:
        about = _ABOUT_SUBJECT.match(rest)
        if about:
            payload = (about.group("rest") or "").strip()
            # "about Dinner plans: See you at 7" → subject / body on first colon.
            if ":" in payload and not re.search(r"(?i)\bbody\s*[:=]", payload):
                left, right = payload.split(":", 1)
                subject = _clean_text(left)
                body = _clean_text(right)
            else:
                # "email Sarah about the trip this weekend" — no colon used to
                # leave body empty so force never fired until a second ask.
                # Use the about-clause as body; short subject from the lead.
                body = _clean_text(payload)
                words = body.split()
                subject = " ".join(words[:6]) if words else "Message"
                if len(words) > 6:
                    subject = subject.rstrip(",.;:") + "…"
        else:
            with_subj = _WITH_SUBJECT.match(rest)
            if with_subj:
                subject = _clean_text(with_subj.group("subject") or "")
            else:
                body_only = _BODY_ONLY.match(rest)
                if body_only:
                    body = _clean_text(body_only.group("body") or "")
                elif rest.strip():
                    # Trailing text without a clear marker — treat as body when short.
                    # Drop a trailing path from the body when we already captured it.
                    body = _clean_text(rest)
                    if attach and attach in body:
                        body = body.replace(attach, "").strip(" \t\"'")
    if attach and not body:
        from pathlib import Path

        body = f"Please see the attached file ({Path(attach).name})."
    return EmailDraft(
        to=to,
        subject=subject,
        body=body,
        source="current",
        attach_path=attach,
    )

def parse_subject_body_followup(text: str) -> tuple[str, str] | None:
    """Parse 'subject: X body: Y' style follow-ups (subject optional)."""
    raw = (text or "").strip()
    if not raw:
        return None
    match = _SUBJECT_BODY_LINE.match(raw)
    if not match:
        return None
    body = _clean_text(match.group("body") or "")
    if not body:
        return None
    subject = _clean_text(match.group("subject") or "")
    return subject, body


def _with_resolved(draft: EmailDraft, book: dict[str, Contact]) -> EmailDraft:
    return EmailDraft(
        to=draft.to,
        subject=draft.subject,
        body=draft.body,
        resolved_to=resolve_email_address(draft.to, book),
        source=draft.source,
        attach_path=draft.attach_path,
    )


def _last_incomplete_email_draft(
    pairs: list[tuple[str, str]], book: dict[str, Contact]
) -> EmailDraft | None:
    """Most recent incomplete compose (has recipient) for aggressive revive."""
    for role, content in reversed(pairs):
        if role != "user":
            continue
        prior = parse_email_utterance(content)
        if prior and prior.to and not prior.complete:
            return _with_resolved(
                EmailDraft(
                    to=prior.to,
                    subject=prior.subject,
                    body=prior.body,
                    source="history",
                    attach_path=prior.attach_path,
                ),
                book,
            )
    return None


def _last_email_draft_any(
    pairs: list[tuple[str, str]], book: dict[str, Contact]
) -> EmailDraft | None:
    """Most recent compose with a recipient (complete or not)."""
    for role, content in reversed(pairs):
        if role != "user":
            continue
        prior = parse_email_utterance(content)
        if prior and prior.to:
            filled = _with_attach_from_history(prior, None, content)
            return _with_resolved(filled, book)
    return None


def _last_complete_email_draft(
    pairs: list[tuple[str, str]], book: dict[str, Contact]
) -> EmailDraft | None:
    """Most recent complete compose in history (for 'send the email' revive)."""
    for role, content in reversed(pairs):
        if role != "user":
            continue
        prior = parse_email_utterance(content)
        if prior and prior.complete:
            return _with_resolved(
                EmailDraft(
                    to=prior.to,
                    subject=prior.subject,
                    body=prior.body,
                    source="history",
                    attach_path=prior.attach_path,
                ),
                book,
            )
        # Also accept a follow-up body turn that completed an earlier draft.
        follow = parse_subject_body_followup(content)
        if follow is None:
            continue
    # Second pass: incomplete "email X about S" + later body line.
    pending: EmailDraft | None = None
    for role, content in pairs:
        if role != "user":
            continue
        prior = parse_email_utterance(content)
        if prior and prior.to and not prior.complete:
            pending = prior
            continue
        if pending is not None:
            follow = parse_subject_body_followup(content)
            if follow is not None:
                subject, body = follow
                return _with_resolved(
                    EmailDraft(
                        to=pending.to,
                        subject=subject or pending.subject,
                        body=body or pending.body,
                        source="history",
                        attach_path=pending.attach_path,
                    ),
                    book,
                )
            body = _clean_text(content)
            if body and not _EMAIL_VERB.match(content) and not _SEND_CONFIRM.match(content):
                return _with_resolved(
                    EmailDraft(
                        to=pending.to,
                        subject=pending.subject,
                        body=body,
                        source="history",
                        attach_path=pending.attach_path,
                    ),
                    book,
                )
    return None


def complete_email_draft(
    user_text: str,
    *,
    history: list[Any] | None = None,
    contacts: dict[str, Contact] | None = None,
) -> EmailDraft | None:
    """Best draft for this turn: current utterance, or fields merged from history."""
    book = contacts if contacts is not None else load_contacts()
    if looks_like_scheduled_send(user_text):
        return None
    if _looks_like_analyze_file_ask(user_text):
        return None
    current = parse_email_utterance(user_text)
    if current is not None:
        current = _with_attach_from_history(current, history, user_text)
    if current and current.complete:
        return _with_resolved(current, book)

    pairs = history_pairs(history or [])
    if not pairs or pairs[-1] != ("user", user_text):
        pairs = [*pairs, ("user", user_text)]

    # Path-only follow-up after a failed/missing attach: revive prior compose.
    path_only = _extract_file_path(user_text)
    if (
        path_only
        and current is None
        and not _EMAIL_VERB.search(user_text or "")
        and not _SEND_CONFIRM.match(user_text or "")
    ):
        pending = _last_email_draft_any(pairs[:-1], book)
        if pending is not None:
            resolved = resolve_attach_path(path_only) or path_only
            from pathlib import Path

            body = pending.body.strip()
            if not body or body.lower().startswith("please see the attached file"):
                body = f"Please see the attached file ({Path(resolved).name})."
            return _with_resolved(
                EmailDraft(
                    to=pending.to,
                    subject=pending.subject or Path(resolved).name,
                    body=body,
                    source="history",
                    attach_path=resolved,
                ),
                book,
            )

    if current and not current.complete:
        # Keep looking for a body/subject only when this turn already has a
        # recipient; a following turn supplies the missing fields.
        return _with_resolved(current, book)

    # Case C: "send the email" / "yes" after a prior draft (R4). Prefer complete;
    # otherwise revive incomplete so preflight / force can finish the fields.
    if current is None and _SEND_CONFIRM.match(user_text or ""):
        revived = _last_complete_email_draft(pairs[:-1], book)
        if revived is not None and revived.complete:
            return revived
        incomplete = _last_incomplete_email_draft(pairs[:-1], book)
        if incomplete is not None:
            return incomplete

    # Case B: current text is NOT an email verb — treat as fields after a pending ask.
    if current is None and user_text.strip() and not _EMAIL_VERB.match(user_text):
        if _SEND_CONFIRM.match(user_text):
            # Already handled in Case C; avoid treating "yes" as a body line.
            return None
        from arelis.core.other_work import looks_like_other_work

        if looks_like_other_work(user_text, history):
            return None
        follow = parse_subject_body_followup(user_text)
        if follow is not None:
            subject, body = follow
        else:
            body = _clean_text(user_text)
            subject = ""
            if len(body) < 2:
                return None
        pending: EmailDraft | None = None
        saw_ask = False
        for role, content in reversed(pairs[:-1]):
            if role == "assistant" and _ASKED_FOR_FIELDS.search(content or ""):
                saw_ask = True
                continue
            if role == "user":
                prior = parse_email_utterance(content)
                if prior and prior.to and not prior.complete:
                    pending = prior
                    break
                if prior and prior.to and prior.complete:
                    if saw_ask:
                        pending = prior
                    break
                if saw_ask and not prior:
                    continue
        if pending is not None:
            merged_subject = subject or pending.subject
            merged_body = body or pending.body
            return _with_resolved(
                EmailDraft(
                    to=pending.to,
                    subject=merged_subject,
                    body=merged_body,
                    source="history",
                    attach_path=pending.attach_path,
                ),
                book,
            )
        # Previous user turn was "email X" incomplete, no assistant ask (stalled).
        for role, content in reversed(pairs[:-1]):
            if role != "user":
                if role == "assistant":
                    break
                continue
            prior = parse_email_utterance(content)
            if prior and prior.to and not prior.complete:
                return _with_resolved(
                    EmailDraft(
                        to=prior.to,
                        subject=subject or prior.subject,
                        body=body or prior.body,
                        source="history",
                        attach_path=prior.attach_path,
                    ),
                    book,
                )
            break

    if current:
        return _with_resolved(current, book)
    return None


def _with_attach_from_history(
    draft: EmailDraft,
    history: list[Any] | None,
    user_text: str,
) -> EmailDraft:
    """Fill attach_path from a named file, chat attachment, or (image-only) last gen."""
    if draft.attach_path.strip():
        resolved = resolve_attach_path(draft.attach_path) or draft.attach_path
        if resolved != draft.attach_path:
            from pathlib import Path

            body = draft.body.strip()
            if not body or body.lower().startswith("please see the attached file"):
                body = f"Please see the attached file ({Path(resolved).name})."
            return EmailDraft(
                to=draft.to,
                subject=draft.subject,
                body=body,
                resolved_to=draft.resolved_to,
                source=draft.source,
                attach_path=resolved,
            )
        return draft

    named = _extract_file_path(user_text)
    if named:
        resolved = resolve_attach_path(named) or named
        from pathlib import Path

        body = draft.body.strip()
        if not body or body.lower() == "please see the attached file.":
            body = f"Please see the attached file ({Path(resolved).name})."
        return EmailDraft(
            to=draft.to,
            subject=draft.subject,
            body=body,
            resolved_to=draft.resolved_to,
            source=draft.source,
            attach_path=resolved,
        )

    # Prefer a staged attachment path from this turn / recent history.
    att = _latest_attachment_path(history, user_text)
    if att:
        from pathlib import Path

        body = draft.body.strip()
        if not body or body.lower() == "please see the attached file.":
            body = f"Please see the attached file ({Path(att).name})."
        return EmailDraft(
            to=draft.to,
            subject=draft.subject,
            body=body,
            resolved_to=draft.resolved_to,
            source=draft.source,
            attach_path=att,
        )

    # Last written document for "email that" / "email the file".
    from arelis.core.document_refs import (
        latest_document_path,
        mentions_recent_document,
    )

    wants_doc = bool(_MEDIA_ATTACH_CUE.search(user_text or "")) or mentions_recent_document(
        user_text or ""
    )
    followup = bool(_EMAIL_SEND_FOLLOWUP.search(user_text or ""))
    if (wants_doc or followup) and not _IMAGE_ATTACH_CUE.search(user_text or ""):
        path = latest_document_path(history or []) or ""
        if path:
            from pathlib import Path

            body = draft.body.strip()
            if not body or body.lower() == "please see the attached file.":
                body = f"Please see the attached file ({Path(path).name})."
            return EmailDraft(
                to=draft.to,
                subject=draft.subject,
                body=body,
                resolved_to=draft.resolved_to,
                source=draft.source,
                attach_path=path,
            )

    # Generated-image fill only for explicit image/photo asks — never for
    # "document" / "file" / spreadsheet turns.
    if not _IMAGE_ATTACH_CUE.search(user_text or ""):
        return draft
    try:
        from arelis.core.image_refs import latest_generated_image_path
    except Exception:
        return draft
    path = latest_generated_image_path(history or []) or ""
    if not path:
        return draft
    from pathlib import Path

    body = draft.body.strip()
    if not body or body.lower() == "please see the attached file.":
        body = f"Please see the attached file ({Path(path).name})."
    return EmailDraft(
        to=draft.to,
        subject=draft.subject,
        body=body,
        resolved_to=draft.resolved_to,
        source=draft.source,
        attach_path=path,
    )


def _latest_attachment_path(
    history: list[Any] | None,
    user_text: str,
) -> str:
    """Best staged/source path from this turn or a recent Attachments block."""
    from arelis.attachments import parse_attachments_from_turn

    chunks: list[str] = [user_text or ""]
    for role, content in reversed(history_pairs(history or [])[-8:]):
        if role == "user":
            chunks.append(content)
    for chunk in chunks:
        rows = parse_attachments_from_turn(chunk)
        if not rows:
            continue
        row = rows[-1]
        source = str(row.get("source_path") or "").strip()
        staged = str(row.get("path") or "").strip()
        for candidate in (source, staged):
            resolved = resolve_attach_path(candidate)
            if resolved:
                return resolved
        if source:
            return source
        if staged:
            return staged
    return ""


def fill_send_email_args(
    args: dict[str, Any],
    draft: EmailDraft | None,
    *,
    contacts: dict[str, Contact] | None = None,
) -> dict[str, Any]:
    """Fill to/subject/body/attach on a tool call from a known draft.

    When the draft is complete (subject+body), those fields are locked — the
    model cannot overwrite them with a different invent. Confirm cards therefore
    show the message that will actually send.
    """
    if draft is None:
        return dict(args)
    out = dict(args)
    named = named_address_in_text(
        f"{draft.to} {draft.resolved_to} {draft.tool_to}".strip()
    ) or repair_email_address(draft.tool_to or draft.to)
    if named and valid_address(named):
        out["to"] = named
    if draft.complete:
        locked_to = named or draft.tool_to
        if locked_to:
            out["to"] = locked_to
        out["subject"] = draft.tool_subject
        out["body"] = draft.tool_body
        if draft.attach_path:
            out["attach"] = draft.attach_path
        return out
    if not str(out.get("to") or "").strip() and draft.tool_to:
        out["to"] = draft.tool_to
    if not str(out.get("subject") or "").strip() and draft.subject:
        out["subject"] = draft.subject
    if not str(out.get("body") or "").strip() and draft.tool_body:
        out["body"] = draft.tool_body
    if draft.attach_path and not str(out.get("attach") or out.get("path") or "").strip():
        out["attach"] = draft.attach_path
    return out


def draft_send_email_args(draft: EmailDraft) -> dict[str, Any]:
    """Concrete send_email kwargs from a complete draft (for inject)."""
    return fill_send_email_args({}, draft)


def email_preflight_nudge(draft: EmailDraft) -> str:
    """System nudge with concrete args (still requires Allow)."""
    if draft.unresolved_named_to:
        who = draft.to.strip()
        return (
            "Intent preflight: the user wants to email "
            f'"{who}" but there is no email address in contacts for that name. '
            "Ask once for the email address (do not invent one, do not silently "
            "mail the user instead). Do not claim the email was sent."
        )
    to = draft.tool_to or "(user)"
    if draft.complete:
        attach = ""
        if draft.attach_path:
            attach = f' attach="{draft.attach_path}"'
        return (
            "Intent preflight: send an email now. Call send_email immediately with "
            f'to="{to}" subject="{draft.tool_subject[:120]}" '
            f'body="{draft.tool_body[:300]}"{attach}. '
            "Do not re-ask for the subject or body. Do not only talk about sending. "
            "Do not web_search for contacts when the address is already literal. "
            "The confirm card is the Allow step."
        )
    missing: list[str] = []
    if not draft.body.strip() and not draft.attach_path:
        missing.append("body")
    need = " and ".join(missing) if missing else "body"
    who = draft.to.strip() or "the recipient"
    return (
        "Intent preflight: the user wants to email "
        f'"{who}" but the {need} is still missing. '
        f"Ask once for the {need} only, or call send_email when you have it. "
        "Do not invent the subject or body."
    )


def email_force_call_notice(draft: EmailDraft) -> str:
    """User-role nudge when the model tried to finish without calling send_email."""
    to = draft.tool_to or "(user)"
    attach = ""
    if draft.attach_path:
        attach = f' attach="{draft.attach_path}"'
    return (
        "You have not called send_email yet. Call it now with "
        f'to="{to}" subject="{draft.tool_subject[:120]}" '
        f'body="{draft.tool_body[:300]}"{attach}. '
        "Do not web_search. Chatting is not sending. "
        "The confirm card will ask the user to Allow."
    )
