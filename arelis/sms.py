"""What a text needs before any radio can send it.

Carrier email-to-SMS used to live here, and it is gone. AT&T closed txt.att.net
in 2025, T-Mobile's gateway went the same way, and Verizon accepts the mail and
then silently drops most of it, so a green "sent" meant Gmail had taken the
message rather than that a phone had shown a bubble. Texts now go out through
the user's own Android handset; see arelis/sms_android.py.

This module is the seam between the tool and whatever radio is behind it:
turning a nickname into a number, capping the body, and writing the confirm
card. Nothing here knows about HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from arelis.contacts import Contact

# The old 160 was the gateway's ceiling, not the transport's: a phone splits a
# long message into segments and the recipient sees one text. This is a runaway
# guard on what the model can put in front of somebody, not a protocol limit.
DEFAULT_MAX_BODY_CHARS = 1600


class SmsSendError(RuntimeError):
    """A send failure whose message is already worded for the user.

    Providers raise this instead of leaking an httpx traceback, because the
    person reading it can fix "the phone is asleep" and cannot fix a status
    code.
    """


class SmsProvider(Protocol):
    async def send(self, *, phone: str, body: str) -> str:
        """Deliver one SMS to an E.164 number. Returns a transport id or ''."""
        ...


@dataclass(frozen=True)
class ResolvedSms:
    """What the confirm card and the tool both need after resolving `to`."""

    contact: Contact | None
    label: str
    phone_display: str
    phone_e164: str


def resolve_operator_sms_target(
    *,
    alias: str = "",
    phone: str = "",
    contacts: dict[str, Contact] | None = None,
) -> ResolvedSms | str:
    """Resolve a human-typed tile send. Digits are enough; a nickname is optional.

    The agent path still uses resolve_sms_target and refuses unknown names.
    The operator already opened this room, so a raw number is a valid address.
    """
    from arelis.contacts import load_contacts, normalize_phone, to_e164

    book = contacts if contacts is not None else load_contacts()
    alias = (alias or "").strip()
    phone = (phone or "").strip()
    if alias:
        resolved = resolve_sms_target(alias, book)
        if not isinstance(resolved, str):
            return resolved
    e164 = to_e164(phone)
    if e164:
        digits = normalize_phone(phone)
        contact = next(
            (
                item
                for item in book.values()
                if item.digits == digits or item.e164 == e164
            ),
            None,
        )
        return ResolvedSms(
            contact=contact,
            label=contact.display_name if contact else (phone or e164),
            phone_display=(contact.phone if contact else "") or phone or e164,
            phone_e164=e164,
        )
    if alias:
        return f"No phone number for {alias}."
    return "No number to send to."


async def send_operator_sms(
    *,
    phone: str,
    body: str,
    provider: SmsProvider,
    max_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> str:
    """Send a text the operator typed. No confirm card, no agent loop."""
    text, _truncated = prepare_body(body, max_chars=max_chars)
    if not text:
        raise SmsSendError("Nothing to send.")
    if not (phone or "").strip():
        raise SmsSendError("No number to send to.")
    return await provider.send(phone=phone, body=text)


def resolve_sms_target(to: str, contacts: dict[str, Contact]) -> ResolvedSms | str:
    """Return a ResolvedSms, or an error string the tool can show the model."""
    from arelis.contacts import list_aliases, resolve_contact

    contact = resolve_contact(to, contacts)
    if contact is None:
        aliases = ", ".join(list_aliases(contacts)) or "(none)"
        return (
            f"Unknown contact {to!r}. Ask the user for their number and save "
            f"them with contacts(action=add), or add them by hand in "
            f"data/contacts.yaml. Known aliases: {aliases}."
        )

    number = contact.e164
    if not number:
        return (
            f"Contact {contact.alias!r} has no usable phone number. Ask the "
            f"user for it, then save it with contacts(action=update)."
        )
    return ResolvedSms(
        contact=contact,
        label=contact.display_name,
        phone_display=contact.phone or contact.digits,
        phone_e164=number,
    )


def format_sms_confirm(to: str, body: str, *, contacts: dict[str, Contact] | None = None) -> str:
    """Full confirm-card text: who, number, how it leaves, body."""
    from arelis.contacts import load_contacts

    book = contacts if contacts is not None else load_contacts()
    resolved = resolve_sms_target(to, book)
    text = (body or "").strip()
    if isinstance(resolved, str):
        return f"To:      {to.strip() or '(missing)'}\n\n{text}"
    return (
        f"To:      {resolved.label} ({resolved.phone_display})\n"
        f"Via:     your phone\n"
        f"(arrives from your number; replies come back to your phone)\n\n"
        f"{text}"
    )


def prepare_body(body: str, *, max_chars: int = DEFAULT_MAX_BODY_CHARS) -> tuple[str, bool]:
    """Return (body, truncated?)."""
    text = (body or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def explain_sms_error(exc: Exception) -> str:
    """Turn a failed send into something the user can act on."""
    if isinstance(exc, SmsSendError):
        return str(exc)
    return f"Send failed: {exc}"
