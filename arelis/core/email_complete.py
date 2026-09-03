"""Fill send_email (to, subject, body) from the current turn and recent chat.

Small models often split "email Brian about dinner" and the body across turns,
then invent a different subject on the confirm card. This module reconstructs a
draft so preflight and the agent loop can nudge with concrete args — still never
sends without Allow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arelis.contacts import Contact, load_contacts, match_contact_label, resolve_contact
from arelis.core.complete_protocol import (
    history_with_current,
    remaining_labels,
    unfinished_call_notice,
)
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
    r"e-?mailed|e-?mails?|"
    r"send\s+(?:an?\s+)?(?:e-?mail|mail)|compose\s+(?:an?\s+)?(?:e-?mail|mail)"
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
    r"e-?mailed|e-?mails?|send\s+(?:an?\s+)?(?:e-?mail|mail)|"
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
    attach_paths: tuple[str, ...] = ()
    wanted_suffixes: tuple[str, ...] = ()
    recipients: tuple[str, ...] = ()
    resolved_recipients: tuple[str, ...] = ()

    @property
    def all_attach_paths(self) -> tuple[str, ...]:
        if self.attach_paths:
            return self.attach_paths
        if self.attach_path.strip():
            return (self.attach_path,)
        return ()

    @property
    def all_tos(self) -> tuple[str, ...]:
        if self.resolved_recipients:
            return self.resolved_recipients
        if self.recipients:
            return self.recipients
        if self.tool_to:
            return (self.tool_to,)
        return (self.to,) if self.to.strip() else ()

    @property
    def unresolved_named_to(self) -> bool:
        """True when a named recipient has no contacts email / literal address."""
        names = self.recipients or ((self.to,) if self.to.strip() else ())
        if not names:
            return False
        resolved = self.resolved_recipients or (
            (self.resolved_to,) if self.resolved_to else ()
        )
        resolved_l = {r.lower() for r in resolved if r}
        for raw in names:
            text = raw.strip()
            if not text or text.lower() in _SELF_TO:
                continue
            if valid_address(repair_email_address(text)):
                continue
            if text.lower() in resolved_l or (
                self.resolved_to and text.lower() == self.to.strip().lower()
            ):
                continue
            return True
        return False

    @property
    def complete(self) -> bool:
        """Ready to force/send: body set, recipient resolvable (or self).

        Subject may be empty — fill/force defaults it so a missing subject alone
        does not skip the Allow card on the first ask. An attachment alone with
        a short body is also enough.
        """
        if self.wanted_suffixes:
            have = {Path(p).suffix.lower() for p in self.all_attach_paths}
            if any(suf not in have for suf in self.wanted_suffixes):
                return False
        if not self.body.strip() and not self.all_attach_paths:
            return False
        if self.unresolved_named_to:
            return False
        return True

    @property
    def tool_to(self) -> str:
        """Preferred `to` arg for send_email (address when known; empty = self)."""
        if self.resolved_recipients:
            return self.resolved_recipients[0]
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
        paths = self.all_attach_paths
        if len(paths) == 1:
            return Path(paths[0]).name or "A message from Arelis"
        if paths:
            return "Documents from Arelis"
        return "A message from Arelis"

    @property
    def tool_body(self) -> str:
        if self.body.strip():
            return self.body.strip()
        paths = self.all_attach_paths
        if paths:
            names = ", ".join(Path(p).name for p in paths)
            label = "files" if len(paths) > 1 else "file"
            return f"Please see the attached {label} ({names})."
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


_ADDR_IN_TEXT = re.compile(
    r"(?i)\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"
)
_COMPOSE_INSTRUCTION = re.compile(
    r"(?i)^\s*(?:,|and|&)?\s*(?:"
    r"be\s+creative|"
    r"make\s+it\s+(?:fun|funny|witty|creative|a\s+test)|"
    r"let\s+(?:them|him|her)\s+know\s+it'?s\s+a\s+test|"
    r"(?:this\s+is\s+)?(?:just\s+)?a\s+test(?:\s*[.!]?\s*)$|"
    r"keep\s+it\s+(?:short|brief|fun|creative)"
    r")\b"
)
_NOT_A_BODY = re.compile(r"(?i)^\s*(?:as\s+well|too|also)\s*[?]?\s*$")
_EMAIL_ALSO_ASK = re.compile(
    r"(?i)\b("
    r"did\s+you\s+(?:also\s+)?(?:e-?mail|send)|"
    r"(?:e-?mail|send).{0,80}\bas\s+well|"
    r"as\s+well\s*[?]?\s*$"
    r")\b"
)
_DEFAULT_TEST_BODY = "This is a test from Arelis. Please ignore."


def named_addresses_in_text(text: str) -> list[str]:
    """Every usable mailbox in free text, including bare @gmail / @yahoo."""
    raw = text or ""
    seen: set[str] = set()
    out: list[str] = []
    for match in _ADDR_IN_TEXT.finditer(raw):
        addr = _clean_to(match.group(1))
        if valid_address(addr) and addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    for match in _BARE_MAIL.finditer(raw):
        fixed = repair_email_address(match.group(0))
        if valid_address(fixed) and fixed.lower() not in seen:
            seen.add(fixed.lower())
            out.append(fixed)
    return out


def named_address_in_text(text: str) -> str:
    """First usable mailbox in free text, including bare @gmail / @yahoo."""
    addrs = named_addresses_in_text(text)
    return addrs[0] if addrs else ""


def looks_like_email_also_ask(text: str) -> bool:
    """True for 'did you email X as well?' — not a new compose body."""
    return bool(_EMAIL_ALSO_ASK.search(text or ""))


def email_remaining(draft: EmailDraft | None, already_sent: set[str] | None) -> list[str]:
    """Addresses still owed on a multi-recipient draft."""
    if draft is None:
        return []
    return remaining_labels(draft.all_tos, already_sent)


def wanted_attach_suffixes(text: str) -> tuple[str, ...]:
    """File suffixes they asked to write and mail (markdown + PDF, etc.)."""
    raw = text or ""
    if not looks_like_compose_email(raw) and not re.search(
        r"(?i)\be-?mailed\b", raw
    ):
        return ()
    found: list[str] = []
    if re.search(r"(?i)\bmarkdown\b|\.md\b", raw):
        found.append(".md")
    if re.search(r"(?i)\bpdf\b|\.pdf\b", raw):
        found.append(".pdf")
    return tuple(found)


def split_attach_args(raw: str) -> list[str]:
    """Split attach= 'a.md, b.pdf' / 'a.md and b.pdf' into paths."""
    text = (raw or "").strip()
    if not text:
        return []
    return [
        part.strip().strip('"').strip("'")
        for part in re.split(r"\s*(?:,|;|\n| and )\s*", text, flags=re.I)
        if part.strip()
    ]


def email_remaining_files(
    draft: EmailDraft | None, already_attached: set[str] | None
) -> list[str]:
    """Written files still owed on a multi-attach draft."""
    if draft is None:
        return []
    have = {Path(s).name.lower() for s in (already_attached or set()) if s}
    return [
        path
        for path in draft.all_attach_paths
        if Path(path).name.lower() not in have
    ]


def email_files_still_owed(draft: EmailDraft | None) -> bool:
    """True when they asked for formats that are not on the draft yet."""
    if draft is None or not draft.wanted_suffixes:
        return False
    have = {Path(p).suffix.lower() for p in draft.all_attach_paths}
    return any(suf not in have for suf in draft.wanted_suffixes)


def email_send_finished(
    draft: EmailDraft | None,
    already_sent: set[str] | None,
    already_attached: set[str] | None = None,
) -> bool:
    """True when every named inbox and every owed file has gone out."""
    if draft is None:
        return False
    if email_remaining(draft, already_sent):
        return False
    if email_files_still_owed(draft):
        return False
    if email_remaining_files(draft, already_attached):
        return False
    return True


def bind_written_files(
    draft: EmailDraft | None,
    written: list[str] | tuple[str, ...],
    user_text: str = "",
) -> EmailDraft | None:
    """Attach this-turn document paths that match the asked formats."""
    if draft is None:
        return None
    wanted = draft.wanted_suffixes or wanted_attach_suffixes(user_text)
    if not wanted:
        return draft
    picked: list[str] = []
    seen: set[str] = set()
    for raw in (*draft.all_attach_paths, *written):
        text = str(raw or "").strip()
        if not text:
            continue
        path = resolve_attach_path(text) or text
        key = path.lower()
        if key in seen:
            continue
        if Path(path).suffix.lower() not in wanted:
            continue
        seen.add(key)
        picked.append(path)
    if not picked:
        return draft if draft.wanted_suffixes else _clone_draft(
            draft, wanted_suffixes=wanted
        )
    names = ", ".join(Path(p).name for p in picked)
    body = draft.body.strip()
    if not body or body.lower().startswith("please see the attached"):
        label = "files" if len(picked) > 1 else "file"
        body = f"Please see the attached {label} ({names})."
    return _clone_draft(
        draft,
        body=body,
        attach_path=picked[0],
        attach_paths=tuple(picked),
        wanted_suffixes=wanted,
    )


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

    from arelis.paths import outputs_dir, state_dir, user_data_dir

    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    root = user_data_dir()
    candidates: list[Path] = [Path(text)]
    name = Path(text).name
    if name:
        candidates.append(outputs_dir() / "documents" / name)
        candidates.append(outputs_dir() / "plots" / name)
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
    addrs = named_addresses_in_text(raw)
    named = addrs[0] if addrs else ""
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
    if addrs:
        after_last = _rest_after_addresses(raw, addrs)
        if after_last.strip():
            rest = after_last
    elif not rest and named:
        after = raw.split(named, 1)
        rest = after[1] if len(after) > 1 else ""
    subject = ""
    body = ""
    explicit_body = False
    quoted = _QUOTED_SUBJECT_BODY.search(raw)
    if quoted:
        subject = _clean_text(quoted.group("subject") or "")
        body = _clean_text(quoted.group("body") or "")
        if attach and not body:
            from pathlib import Path

            body = f"Please see the attached file ({Path(attach).name})."
        recips = tuple(addrs) if addrs else ((to,) if to else ())
        return EmailDraft(
            to=to,
            subject=subject,
            body=body,
            source="current",
            attach_path=attach,
            recipients=recips,
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
        explicit_body = True
    else:
        about = _ABOUT_SUBJECT.match(rest)
        if about:
            payload = (about.group("rest") or "").strip()
            explicit_body = True
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
                    if re.match(r"(?i)^\s*(?:that|saying)\b", rest):
                        explicit_body = True
                elif rest.strip():
                    # Trailing text without a clear marker — treat as body when short.
                    # Drop a trailing path from the body when we already captured it.
                    body = _clean_text(rest)
                    if attach and attach in body:
                        body = body.replace(attach, "").strip(" \t\"'")
    if attach and not body:
        from pathlib import Path

        body = f"Please see the attached file ({Path(attach).name})."
    if not explicit_body:
        body = _normalize_compose_body(body)
    recips = tuple(addrs) if addrs else ((to,) if to else ())
    return EmailDraft(
        to=to,
        subject=subject,
        body=body,
        source="current",
        attach_path=attach,
        recipients=recips,
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


def _clone_draft(draft: EmailDraft, **overrides: Any) -> EmailDraft:
    data = {
        "to": draft.to,
        "subject": draft.subject,
        "body": draft.body,
        "resolved_to": draft.resolved_to,
        "source": draft.source,
        "attach_path": draft.attach_path,
        "attach_paths": draft.attach_paths,
        "wanted_suffixes": draft.wanted_suffixes,
        "recipients": draft.recipients,
        "resolved_recipients": draft.resolved_recipients,
    }
    data.update(overrides)
    return EmailDraft(**data)


def _with_resolved(draft: EmailDraft, book: dict[str, Contact]) -> EmailDraft:
    names = draft.recipients or ((draft.to,) if draft.to.strip() else ())
    resolved: list[str] = []
    seen: set[str] = set()
    for name in names:
        addr = resolve_email_address(name, book)
        if addr and addr.lower() not in seen:
            seen.add(addr.lower())
            resolved.append(addr)
    primary = resolved[0] if resolved else resolve_email_address(draft.to, book)
    return _clone_draft(
        draft,
        resolved_to=primary,
        recipients=tuple(names),
        resolved_recipients=tuple(resolved),
    )


def _rest_after_addresses(raw: str, addrs: list[str]) -> str:
    if not addrs:
        return ""
    last = addrs[-1]
    idx = raw.lower().rfind(last.lower())
    if idx < 0:
        return ""
    return raw[idx + len(last) :]


def _normalize_compose_body(body: str) -> str:
    text = _clean_text(body)
    if _NOT_A_BODY.match(text):
        return ""
    if _looks_like_compose_instruction(text):
        return _DEFAULT_TEST_BODY
    return text


def _looks_like_compose_instruction(text: str) -> bool:
    raw = (text or "").strip(" ,.;")
    if not raw:
        return False
    return bool(_COMPOSE_INSTRUCTION.match(raw))


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
                _clone_draft(prior, source="history"),
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
                _clone_draft(prior, source="history"),
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
                    _clone_draft(
                        pending,
                        subject=subject or pending.subject,
                        body=body or pending.body,
                        source="history",
                    ),
                    book,
                )
            body = _clean_text(content)
            if body and not _EMAIL_VERB.match(content) and not _SEND_CONFIRM.match(content):
                return _with_resolved(
                    _clone_draft(
                        pending,
                        body=body,
                        source="history",
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
        suffixes = wanted_attach_suffixes(user_text)
        if suffixes and not current.wanted_suffixes:
            current = _clone_draft(current, wanted_suffixes=suffixes)
        current = _with_attach_from_history(current, history, user_text)
    if looks_like_email_also_ask(user_text):
        pairs = history_with_current(history, user_text)
        prior = _last_complete_email_draft(pairs[:-1], book) or _last_email_draft_any(
            pairs[:-1], book
        )
        if prior is not None:
            names = list(prior.recipients or ((prior.to,) if prior.to else ()))
            for addr in named_addresses_in_text(user_text):
                if addr.lower() not in {n.lower() for n in names}:
                    names.append(addr)
            return _with_resolved(
                _clone_draft(
                    prior,
                    to=names[0] if names else prior.to,
                    recipients=tuple(names),
                    body=prior.body or _DEFAULT_TEST_BODY,
                    source="history",
                ),
                book,
            )
    if current and current.complete:
        return _with_resolved(current, book)

    pairs = history_with_current(history, user_text)

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
                _clone_draft(
                    pending,
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
        from arelis.core.other_work import looks_like_other_work, looks_like_sent_compose

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
            if role == "assistant":
                if looks_like_sent_compose(content or ""):
                    return None
                if _ASKED_FOR_FIELDS.search(content or ""):
                    saw_ask = True
                continue
            if role == "user":
                prior = parse_email_utterance(content)
                if prior and prior.to and not prior.complete:
                    if saw_ask:
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
                _clone_draft(
                    pending,
                    subject=merged_subject,
                    body=merged_body,
                    source="history",
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
                    _clone_draft(
                        prior,
                        subject=subject or prior.subject,
                        body=body or prior.body,
                        source="history",
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
            return _clone_draft(draft, body=body, attach_path=resolved)
        return draft

    named = _extract_file_path(user_text)
    if named:
        resolved = resolve_attach_path(named) or named
        from pathlib import Path

        body = draft.body.strip()
        if not body or body.lower() == "please see the attached file.":
            body = f"Please see the attached file ({Path(resolved).name})."
        return _clone_draft(draft, body=body, attach_path=resolved)

    # Prefer a staged attachment path from this turn / recent history.
    att = _latest_attachment_path(history, user_text)
    if att:
        from pathlib import Path

        body = draft.body.strip()
        if not body or body.lower() == "please see the attached file.":
            body = f"Please see the attached file ({Path(att).name})."
        return _clone_draft(draft, body=body, attach_path=att)

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
            return _clone_draft(draft, body=body, attach_path=path)

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
    return _clone_draft(draft, body=body, attach_path=path)


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
    already_sent: set[str] | None = None,
) -> dict[str, Any]:
    """Fill to/subject/body/attach on a tool call from a known draft.

    When the draft is complete (subject+body), those fields are locked — the
    model cannot overwrite them with a different invent. Confirm cards therefore
    show the message that will actually send. For two named inboxes, `to` is
    the next address not already sent this turn.
    """
    if draft is None:
        return dict(args)
    out = dict(args)
    remaining = email_remaining(draft, already_sent)
    next_to = remaining[0] if remaining else draft.tool_to
    if next_to and not valid_address(repair_email_address(next_to)):
        next_to = draft.tool_to or next_to
    model_to = repair_email_address(str(out.get("to") or "").strip())
    intended = {a.lower() for a in draft.all_tos}
    sent = {s.lower() for s in (already_sent or set())}
    if (
        model_to
        and valid_address(model_to)
        and model_to.lower() in intended
        and model_to.lower() not in sent
    ):
        next_to = model_to
    if next_to:
        out["to"] = next_to
    if draft.complete:
        out["subject"] = draft.tool_subject
        out["body"] = draft.tool_body
        if draft.all_attach_paths:
            out["attach"] = ", ".join(draft.all_attach_paths)
        return out
    if not str(out.get("subject") or "").strip() and draft.subject:
        out["subject"] = draft.subject
    if not str(out.get("body") or "").strip() and draft.tool_body:
        out["body"] = draft.tool_body
    if draft.all_attach_paths and not str(
        out.get("attach") or out.get("path") or ""
    ).strip():
        out["attach"] = ", ".join(draft.all_attach_paths)
    return out


def draft_send_email_args(
    draft: EmailDraft, *, already_sent: set[str] | None = None
) -> dict[str, Any]:
    """Concrete send_email kwargs from a complete draft (for inject)."""
    return fill_send_email_args({}, draft, already_sent=already_sent)


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
    tos = ", ".join(draft.all_tos) or draft.tool_to or "(user)"
    to = draft.tool_to or "(user)"
    if email_files_still_owed(draft):
        kinds = ", ".join(s.lstrip(".") for s in draft.wanted_suffixes)
        return (
            "Intent preflight: write the asked files with document first "
            f"({kinds}), then call send_email once to {tos} with attach= "
            "those paths comma-separated (markdown and PDF on the same "
            "message). Do not send until both files exist. "
            "The confirm card is the Allow step."
        )
    if draft.complete:
        attach = ""
        if draft.all_attach_paths:
            attach = f' attach="{ ", ".join(draft.all_attach_paths) }"'
        if len(draft.all_tos) > 1:
            return (
                "Intent preflight: send an email to each address now. Call "
                f"send_email once per address in order ({tos}) with the same "
                f'subject="{draft.tool_subject[:120]}" '
                f'body="{draft.tool_body[:300]}"{attach}. '
                "Do not drop a named inbox. Each send needs its own Allow."
            )
        return (
            "Intent preflight: send an email now. Call send_email immediately with "
            f'to="{to}" subject="{draft.tool_subject[:120]}" '
            f'body="{draft.tool_body[:300]}"{attach}. '
            "Do not re-ask for the subject or body. Do not only talk about sending. "
            "Do not web_search for contacts when the address is already literal. "
            "The confirm card is the Allow step."
        )
    missing: list[str] = []
    if not draft.body.strip() and not draft.all_attach_paths:
        missing.append("body")
    need = " and ".join(missing) if missing else "body"
    who = draft.to.strip() or "the recipient"
    return (
        "Intent preflight: the user wants to email "
        f'"{who}" but the {need} is still missing. '
        f"Ask once for the {need} only, or call send_email when you have it. "
        "Do not invent the subject or body."
    )


def email_force_call_notice(
    draft: EmailDraft, *, already_sent: set[str] | None = None
) -> str:
    """User-role nudge when the model tried to finish without calling send_email."""
    remaining = email_remaining(draft, already_sent)
    to = remaining[0] if remaining else (draft.tool_to or "(user)")
    extra = ""
    if len(remaining) > 1:
        extra = f" Then repeat for: {', '.join(remaining[1:])}."
    attach = ""
    if draft.all_attach_paths:
        attach = f' attach="{ ", ".join(draft.all_attach_paths) }"'
    return unfinished_call_notice(
        "send_email",
        (
            f'Call it now with to="{to}" subject="{draft.tool_subject[:120]}" '
            f'body="{draft.tool_body[:300]}"{attach}'
        ),
        extra=extra,
        after=(
            "Do not web_search. Chatting is not sending. "
            "The confirm card will ask the user to Allow."
        ),
    )
