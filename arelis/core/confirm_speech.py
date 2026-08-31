"""Speech acts for conversation mode: allow, deny, stop, hangup, draft edits.

Whole utterance only for decisions and hangup. Room chat and "I don't know"
must not allow a send. Stop is the turn, not deny-this-step. Hangup ends
the hands-free call. Pause / go hold her Chrome drive. After a stop,
ordinary talk goes to the model with a one-line note — no resume phrase list.
"""

from __future__ import annotations

import re
from typing import Any

# Whole utterance only.
_ALLOW_TURN = re.compile(
    r"(?i)^\s*(?:"
    r"rest of this ask|"
    r"allow(?:\s+the)?\s+rest|"
    r"do the rest|"
    r"just do (?:it )?all|"
    r"allow (?:the )?rest of (?:this|the) ask"
    r")\s*[.!]?\s*$"
)
_ALLOW = re.compile(
    r"(?i)^\s*(?:"
    r"yes|yeah|yep|yup|ok|okay|sure|"
    r"allow|approve|"
    r"go ahead|do it|please do|"
    r"keep going|continue"
    r")\s*[.!]?\s*$"
)
_STOP = re.compile(
    r"(?i)^\s*(?:"
    r"stop|cancel|"
    r"cut it out|that's enough|thats enough|"
    r"stop (?:it|that|please|talking)|"
    r"be quiet|shut up|hush"
    r")\s*[.!]?\s*$"
)
# Hang up conversation. Whole utterance only. Not "stop" (that cancels a
# turn) and not "stop talking" (that hushes her and stays in the call).
_HANGUP = re.compile(
    r"(?i)^\s*(?:"
    r"good\s*bye|bye|"
    r"good\s*night|"
    r"that'?s\s+(?:all|it)|that\s+is\s+(?:all|it)|"
    r"we(?:'re|\s+are)\s+done|"
    r"stop\s+listening|"
    r"go(?:\s+back)?\s+to\s+sleep|"
    r"(?:i(?:'?m|\s+am)\s+)?done\s+talking|"
    r"talk\s+later|"
    r"see\s+y(?:a|ou)(?:\s+later)?"
    r")\s*[.!]?\s*$"
)
_DRIVE_PAUSE = re.compile(
    r"(?i)^\s*(?:"
    r"pause|"
    r"hold on|hold up|hang on|"
    r"wait(?: a (?:sec(?:ond)?|minute))?"
    r")\s*[.!]?\s*$"
)
_DRIVE_RESUME = re.compile(
    r"(?i)^\s*(?:"
    r"go|resume|unpause|unfreeze|"
    r"keep going|continue|go ahead"
    r")\s*[.!]?\s*$"
)
_DENY = re.compile(
    r"(?i)^\s*(?:"
    r"no|nope|nah|"
    r"deny|"
    r"don't|dont|do not|"
    r"never|not now"
    r")\s*[.!]?\s*$"
)

# Spoken corrections on an open send card. Leading "no" is "change this", not deny.
_BODY_EDIT = re.compile(
    r"(?i)^\s*(?:(?:no|nope|nah|actually|wait)[,.]?\s+)?"
    r"(?:"
    r"(?:just\s+|please\s+)?tell(?:ing)?\s+(?:her|him|them)\s+(?:that\s+|to\s+)?"
    r"|(?:just\s+|please\s+)?say(?:ing)?\s+(?:that\s+)?"
    r"|have\s+it\s+say\s+"
    r"|change\s+(?:it|the\s+(?:body|text|message))?\s*to\s+"
    r"|make\s+it\s+"
    r"|body\s*[:=]\s+"
    r")"
    r"(?P<body>.+)$"
)
_TO_EDIT = re.compile(
    r"(?i)^\s*(?:(?:no|actually|wait)[,.]?\s+)?"
    r"(?:(?:send|text|email)\s+(?:it\s+)?)?to\s+"
    r"(?P<to>.+?)(?:\s+instead)?\s*$"
)
_SUBJECT_EDIT = re.compile(
    r"(?i)^\s*(?:(?:no|actually|wait)[,.]?\s+)?"
    r"subject\s*[:=]\s*(?P<subject>.+)$"
)
_PRONOUN_TO = frozenset({"her", "him", "them"})


def classify_voice_act(text: str) -> str | None:
    """Return a speech act, or None when this is ordinary talk.

    Values: ``allow``, ``allow_turn``, ``skip`` (deny), ``stop``.
    Empty string is not a decision (Enter on an empty composer stays allow).
    After a stop, ordinary talk goes to the model with a one-line note —
    no resume phrase list.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _ALLOW_TURN.match(raw):
        return "allow_turn"
    if _STOP.match(raw):
        return "stop"
    if _ALLOW.match(raw):
        return "allow"
    if _DENY.match(raw):
        return "skip"
    return None


def classify_drive_act(text: str) -> str | None:
    """``pause`` / ``resume`` for her Chrome drive, or None.

    Whole utterance only. Physics ``pause`` is classified first in the
    orchestrator when Reality is open. ``go ahead`` is also allow — the
    caller uses resume only while the drive is held.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _DRIVE_PAUSE.match(raw):
        return "pause"
    if _DRIVE_RESUME.match(raw):
        return "resume"
    return None


def classify_confirm_utterance(text: str) -> str | None:
    """Card-facing wrapper: ``allow``, ``allow_turn``, ``skip``, or ``stop``.

    Internal deny wire is still skip.
    """
    act = classify_voice_act(text)
    if act in {"allow", "allow_turn", "skip", "stop"}:
        return act
    return None


def classify_hangup(text: str) -> bool:
    """True when the whole utterance ends the hands-free call.

    Confirm cards keep the floor: "goodbye" on a send card is not a hangup.
    """
    return bool(_HANGUP.match((text or "").strip()))


def stopped_ask_note(last: str) -> str:
    """One line for the model after a stop. No instructions beyond the fact."""
    last = (last or "").strip()
    if not last:
        return ""
    return (
        "You were stopped. Last ask:\n"
        f"{last}\n"
        "Continue that only if they want it. "
        "If they were not talking to you, stay quiet."
    )


def apply_confirm_edit(tool: str, args: dict[str, Any], text: str) -> bool:
    """Mutate ``args`` from a spoken correction. True when something changed.

    First tools: send_sms and send_email. Other cards stay as-is (ignored).
    """
    raw = (text or "").strip()
    if not raw or not args:
        return False
    name = (tool or "").strip().lower()
    if name == "send_sms":
        return _edit_sms(args, raw)
    if name == "send_email":
        return _edit_email(args, raw)
    return False


def _clean_piece(value: str) -> str:
    return (value or "").strip().strip("\"'").rstrip(".,!").strip()


def _edit_sms(args: dict[str, Any], raw: str) -> bool:
    from arelis.core.sms_complete import parse_sms_utterance

    changed = False
    draft = parse_sms_utterance(raw)
    if draft is not None:
        body = _clean_piece(draft.body or "")
        if body:
            args["body"] = body
            changed = True
        to = _clean_piece(draft.to or "")
        if to and to.lower() not in _PRONOUN_TO:
            args["to"] = to
            changed = True
        if changed:
            return True
    body_m = _BODY_EDIT.match(raw)
    if body_m:
        body = _clean_piece(body_m.group("body") or "")
        if body:
            args["body"] = body
            changed = True
    to_m = _TO_EDIT.match(raw)
    if to_m:
        to = _clean_piece(to_m.group("to") or "")
        to = re.sub(r"(?i)\s+instead$", "", to).strip()
        if to and to.lower() not in _PRONOUN_TO:
            args["to"] = to
            changed = True
    return changed


def _edit_email(args: dict[str, Any], raw: str) -> bool:
    from arelis.core.email_complete import parse_email_utterance, parse_subject_body_followup

    changed = False
    follow = parse_subject_body_followup(raw)
    if follow is not None:
        subject, body = follow
        if subject:
            args["subject"] = subject
            changed = True
        if body:
            args["body"] = body
            changed = True
        if changed:
            return True
    draft = parse_email_utterance(raw)
    if draft is not None:
        if draft.to:
            args["to"] = draft.to
            changed = True
        if draft.subject:
            args["subject"] = draft.subject
            changed = True
        if draft.body:
            args["body"] = draft.body
            changed = True
        if changed:
            return True
    subj_m = _SUBJECT_EDIT.match(raw)
    if subj_m:
        subject = _clean_piece(subj_m.group("subject") or "")
        if subject:
            args["subject"] = subject
            changed = True
    body_m = _BODY_EDIT.match(raw)
    if body_m:
        body = _clean_piece(body_m.group("body") or "")
        if body:
            args["body"] = body
            changed = True
    to_m = _TO_EDIT.match(raw)
    if to_m:
        to = _clean_piece(to_m.group("to") or "")
        to = re.sub(r"(?i)\s+instead$", "", to).strip()
        if to:
            args["to"] = to
            changed = True
    return changed
