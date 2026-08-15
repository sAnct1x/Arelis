"""Named people for SMS (and later anything that needs a nickname → address).

Loaded from data/contacts.yaml, gitignored like secrets and profile. The model
passes aliases such as "wife" or "my mom"; this module is what turns those into
a phone number without inventing one.

Each contact has a primary key plus optional `aliases` (myself, my phone, mum…).
The contacts tool can list/add/update/remove entries in the same file.

A `carrier` field used to be required, back when texts went out through carrier
email gateways. Those are dead and the field went with them: the phone number is
the whole address now, and an entry only needs an id and a number.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

log = logging.getLogger(__name__)

CONTACTS_PATH = state_dir() / "contacts.yaml"

_LEADING_MY = re.compile(r"^my\s+", re.IGNORECASE)
_NON_DIGIT = re.compile(r"\D+")
# Google Messages notification titles often include emoji / punctuation.
_LABEL_NOISE = re.compile(r"[^\w\s+\-'.]", re.UNICODE)


def _norm_key(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _norm_label(value: str) -> str:
    """Normalize a notification title for contact matching."""
    cleaned = _LABEL_NOISE.sub(" ", value or "")
    return _norm_key(cleaned)


@dataclass(frozen=True)
class Contact:
    alias: str
    name: str
    phone: str
    digits: str
    email: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display_name(self) -> str:
        return self.name or self.alias

    @property
    def e164(self) -> str:
        """The number in the form a phone gateway wants it."""
        return to_e164(self.phone)

    @property
    def keys(self) -> frozenset[str]:
        """All normalized nicknames that resolve to this person."""
        out = {_norm_key(self.alias)}
        for item in self.aliases:
            key = _norm_key(item)
            if key:
                out.add(key)
        return frozenset(out)


def normalize_phone(value: str) -> str:
    """Digits only. US numbers keep the last 10 (drop a leading country 1)."""
    digits = _NON_DIGIT.sub("", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def to_e164(value: str, *, country_code: str = "1") -> str:
    """+15551112222 from anything a person would plausibly type.

    normalize_phone is for matching, where "(555) 111-2222" and "+1 555 111
    2222" have to compare equal. This is for dialling, where the country code is
    the part that must not be dropped.

    Ten digits are assumed to be North American, since that is the only book
    this has. A number written with a leading + is trusted as already
    international, so an overseas contact works if it is written out in full.
    """
    raw = (value or "").strip()
    digits = _NON_DIGIT.sub("", raw)
    if not digits:
        return ""
    if raw.startswith("+") or len(digits) > 10:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+{country_code}{digits}"
    return f"+{digits}"


def load_contacts(path: Path | None = None) -> dict[str, Contact]:
    """Return primary-alias → Contact. Empty dict when the file is missing or blank."""
    path = path or CONTACTS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return {}

    section = raw.get("contacts") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return {}

    out: dict[str, Contact] = {}
    for key, value in section.items():
        alias = _norm_key(str(key or ""))
        if not alias or not isinstance(value, dict):
            continue
        phone = str(value.get("phone") or "").strip()
        digits = normalize_phone(phone)
        email = str(value.get("email") or "").strip()
        # An entry with no number cannot be texted, and a half-written contact
        # in the book is worse than none: it resolves, then fails at send time.
        if not digits:
            continue
        extra: list[str] = []
        raw_aliases = value.get("aliases") or []
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        if isinstance(raw_aliases, list):
            for item in raw_aliases:
                norm = _norm_key(str(item or ""))
                if norm and norm != alias:
                    extra.append(norm)
        out[alias] = Contact(
            alias=alias,
            name=str(value.get("name") or "").strip(),
            phone=phone,
            digits=digits,
            email=email,
            aliases=tuple(extra),
        )
    return out


def resolve_contact(
    to: str,
    contacts: dict[str, Contact] | None = None,
) -> Contact | None:
    """Match a primary key, any alias, optional leading 'my ', or a phone number."""
    contacts = contacts if contacts is not None else load_contacts()
    raw = (to or "").strip()
    if not raw:
        return None

    candidates = [_norm_key(raw)]
    stripped = _LEADING_MY.sub("", raw).strip()
    stripped_key = _norm_key(stripped)
    if stripped_key and stripped_key not in candidates:
        candidates.append(stripped_key)

    for contact in contacts.values():
        keys = contact.keys
        for cand in candidates:
            if cand in keys:
                return contact

    digits = normalize_phone(raw)
    if digits:
        for contact in contacts.values():
            if contact.digits and contact.digits == digits:
                return contact
    return None


# Public-web lookup for a person already in the book. After the name is
# stripped, the remainder must be empty or only these words — searching
# "<contact name> interferometer paper" stays allowed.
_CONTACT_WEB_LOOKUP = re.compile(
    r"(?:"
    r"(?:phone(?:\s+number)?|number|email|e-mail|"
    r"contact(?:s)?(?:\s+info(?:rmation)?)?|info(?:rmation)?|"
    r"address|who\s+is|look\s*up|find|search|text|sms|call)"
    r"(?:\s+|$))+"
    r"",
    re.IGNORECASE,
)


def web_search_targets_known_contact(
    query: str,
    contacts: dict[str, Contact] | None = None,
) -> Contact | None:
    """Return the book entry when this web_search is looking up a known person.

    A query that is just their name/alias, or their name plus contact-info
    wording, must not hit the public web. Research queries that happen to
    contain the name stay allowed.
    """
    book = contacts if contacts is not None else load_contacts()
    q = _norm_label(query)
    if not q or not book:
        return None
    best: Contact | None = None
    best_len = 0
    for contact in book.values():
        labels = (contact.alias, contact.name, *contact.aliases)
        for label in labels:
            key = _norm_label(label)
            if len(key) < 3:
                continue
            if key == q or f" {key} " in f" {q} ":
                if len(key) > best_len:
                    best = contact
                    best_len = len(key)
    if best is None:
        return None
    remainder = q
    labels = sorted(
        {_norm_label(x) for x in (best.alias, best.name, *best.aliases)},
        key=len,
        reverse=True,
    )
    for key in labels:
        if len(key) >= 3:
            remainder = remainder.replace(key, " ")
    remainder = " ".join(remainder.split())
    if not remainder:
        return best
    if _CONTACT_WEB_LOOKUP.fullmatch(remainder):
        return best
    return None


def match_contact_label(
    label: str,
    contacts: dict[str, Contact] | None = None,
) -> Contact | None:
    """Match a Google Messages-style title to a contact name or alias."""
    contacts = contacts if contacts is not None else load_contacts()
    key = _norm_label(label)
    if not key:
        return None
    stripped = _norm_label(_LEADING_MY.sub("", label))
    candidates = {key}
    if stripped:
        candidates.add(stripped)

    for contact in contacts.values():
        names = {_norm_label(contact.alias), _norm_label(contact.name)}
        names.update(_norm_label(a) for a in contact.aliases)
        names.discard("")
        if candidates & names:
            return contact
        # Title contains the contact name ("Robin Hale 💋") or vice versa.
        for cand in candidates:
            for name in names:
                if len(name) >= 3 and (name in cand or cand in name):
                    return contact
    return None


_EMAIL_IN_ANGLE = re.compile(r"<([^>]+@[^>]+)>")
_EMAIL_BARE = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+")


def match_mail_sender(
    from_header: str,
    contacts: dict[str, Contact] | None = None,
) -> Contact | None:
    """Match an email From header to a contacts.yaml address (not a name guess)."""
    contacts = contacts if contacts is not None else load_contacts()
    header = from_header or ""
    found: list[str] = []
    for match in _EMAIL_IN_ANGLE.finditer(header):
        found.append(match.group(1).strip().lower())
    if not found:
        bare = _EMAIL_BARE.search(header)
        if bare:
            found.append(bare.group(0).strip().lower())
    if not found:
        return None
    for contact in contacts.values():
        addr = (contact.email or "").strip().lower()
        if addr and addr in found:
            return contact
    return None


def list_aliases(contacts: dict[str, Contact] | None = None) -> list[str]:
    contacts = contacts if contacts is not None else load_contacts()
    keys: set[str] = set()
    for contact in contacts.values():
        keys.update(contact.keys)
    return sorted(keys)


def parse_aliases(raw: Any) -> list[str]:
    """Normalize aliases from a list, comma-string, or empty."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,;]", raw)
    elif isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = [str(raw)]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = _norm_key(part)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def contact_to_mapping(contact: Contact) -> dict[str, Any]:
    """YAML-friendly dict for one contact (no primary key)."""
    data: dict[str, Any] = {
        "name": contact.name,
        "phone": contact.phone,
    }
    if contact.email:
        data["email"] = contact.email
    if contact.aliases:
        data["aliases"] = list(contact.aliases)
    return data


def format_contact(contact: Contact) -> str:
    nicks = ", ".join([contact.alias, *contact.aliases])
    phone = contact.phone or "(none)"
    lines = [
        f"{contact.display_name} [{contact.alias}]",
        f"  SMS phone: {phone}",
        f"  also:    {nicks}",
    ]
    if contact.email:
        lines.append(f"  email:   {contact.email} (not a phone number)")
    else:
        lines.append("  email:   (none)")
    lines.append(
        "Use SMS phone for texts. Do not report another contact's email as this phone."
    )
    return "\n".join(lines)


def format_contact_spoken(
    data: dict[str, Any],
    *,
    field: str = "who",
) -> str:
    """One short line for chat/voice. Never include the model-only hint."""
    name = str(data.get("name") or "").strip()
    alias = str(data.get("id") or data.get("alias") or "").strip()
    phone = str(data.get("phone") or "").strip()
    email = str(data.get("email") or "").strip()
    who = name or alias or "That contact"
    if field == "phone":
        if phone:
            return f"{who}'s SMS phone is {phone}."
        return f"{who} has no SMS phone in contacts."
    if field == "email":
        if email:
            return f"{who}'s email is {email}."
        return f"{who} has no email in contacts."
    if alias and name:
        lead = f"{name} is listed as {alias}."
    else:
        lead = f"{who}."
    if phone:
        return f"{lead} SMS phone {phone}."
    return lead


# Keep short: this rides every turn like the standing profile. Cap so a long
# contacts book cannot crowd out the persona and recent chat.
_MAX_CONTACTS_PROMPT_CHARS = 900


def contacts_prompt_line(path: Path | None = None) -> str:
    """One system line listing SMS/email aliases the model may pass to tools.

    Without this, a 7B keeps asking for the message body instead of calling
    the tool, and invents whether someone is in the book. Empty when the file
    is missing or has no entries.
    """
    book = load_contacts(path)
    if not book:
        return ""
    parts: list[str] = []
    email_parts: list[str] = []
    for alias in sorted(book):
        contact = book[alias]
        label = contact.name or alias
        extras = list(contact.aliases[:3])
        if extras:
            parts.append(f"{alias} ({label}; also {', '.join(extras)})")
        else:
            parts.append(f"{alias} ({label})")
        if contact.email:
            email_parts.append(f"{alias}→{contact.email}")
    body = "; ".join(parts)
    text = (
        "Contacts — when the user asks to text someone, call send_sms with "
        f"to set to one of these aliases: {body}. "
    )
    if email_parts:
        emails = "; ".join(email_parts)
        text += (
            "Email aliases are not phone numbers. When they ask to email "
            "someone listed here, call send_email with to set to that alias "
            f"(email only: {emails}). "
            "When they ask who someone is, call contacts(action=get) and "
            "read that tool's phone line — do not reuse another alias's email. "
        )
    text += (
        "If they name someone who is not listed, say so and offer to add them "
        "with the contacts tool (need a short id and phone; email optional). "
        "Never invent a phone number or email address."
    )
    if len(text) > _MAX_CONTACTS_PROMPT_CHARS:
        text = text[: _MAX_CONTACTS_PROMPT_CHARS - 1].rstrip() + "…"
    return text


def save_contacts(
    contacts: dict[str, Contact],
    path: Path | None = None,
) -> None:
    """Rewrite data/contacts.yaml from the in-memory book."""
    path = path or CONTACTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "contacts": {
            key: contact_to_mapping(contact) for key, contact in contacts.items()
        }
    }
    text = (
        "# Gitignored. Named people for send_sms.\n"
        "# Template: data/contacts.example.yaml\n"
        "# Edited by Arelis (contacts tool) or by hand.\n\n"
        + yaml.safe_dump(
            body, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    )
    path.write_text(text, encoding="utf-8")


def find_alias_owner(
    nickname: str,
    contacts: dict[str, Contact],
    *,
    excluding: str = "",
) -> Contact | None:
    """Who already owns this nickname, if anyone other than excluding."""
    key = _norm_key(nickname)
    if not key:
        return None
    skip = _norm_key(excluding)
    for contact in contacts.values():
        if contact.alias == skip:
            continue
        if key in contact.keys:
            return contact
    return None


def add_contact(
    *,
    key: str,
    name: str = "",
    phone: str = "",
    aliases: Any = None,
    email: str = "",
    path: Path | None = None,
) -> Contact | str:
    """Create a new contact. Fails if the id already exists."""
    path = path or CONTACTS_PATH
    book = load_contacts(path)
    primary = _norm_key(key)
    if not primary:
        return "Contact id is missing. Pick a short key like 'dave' or 'coach'."
    if primary in book:
        return (
            f"Contact {primary!r} already exists. Use action=update to change "
            f"them, or pick a different id."
        )
    owner = find_alias_owner(primary, book)
    if owner is not None:
        return (
            f"{primary!r} is already a nickname for {owner.display_name} "
            f"({owner.alias}). Pick a different id."
        )
    return _write_contact(
        book,
        primary=primary,
        base=None,
        name=name,
        phone=phone,
        aliases=aliases,
        email=email,
        replace_aliases=True,
        path=path,
    )


def update_contact(
    *,
    who: str,
    name: str = "",
    phone: str = "",
    aliases: Any = None,
    email: str = "",
    replace_aliases: bool = False,
    path: Path | None = None,
) -> Contact | str:
    """Update an existing contact (matched by any nickname)."""
    path = path or CONTACTS_PATH
    book = load_contacts(path)
    existing = resolve_contact(who, book)
    if existing is None:
        return (
            f"No contact matches {who!r}. Use action=add to create one, or "
            f"list contacts first."
        )
    return _write_contact(
        book,
        primary=existing.alias,
        base=existing,
        name=name,
        phone=phone,
        aliases=aliases,
        email=email,
        replace_aliases=replace_aliases,
        path=path,
    )


def _write_contact(
    book: dict[str, Contact],
    *,
    primary: str,
    base: Contact | None,
    name: str,
    phone: str,
    aliases: Any,
    email: str,
    replace_aliases: bool,
    path: Path,
) -> Contact | str:
    new_name = (name or "").strip() or (base.name if base else "")
    new_phone = (phone or "").strip() or (base.phone if base else "")
    new_email = (email or "").strip() or (base.email if base else "")
    digits = normalize_phone(new_phone)

    if not digits:
        return "Need a phone number. Ask the user for it before saving."

    if aliases is None and base is not None:
        new_aliases = list(base.aliases)
    else:
        new_aliases = parse_aliases(aliases)
        if base is not None and not replace_aliases:
            merged = list(base.aliases)
            for item in new_aliases:
                if item not in merged and item != primary:
                    merged.append(item)
            new_aliases = merged

    new_aliases = [a for a in new_aliases if a != primary]

    for nick in [primary, *new_aliases]:
        owner = find_alias_owner(nick, book, excluding=primary)
        if owner is not None:
            return (
                f"Nickname {nick!r} is already used by {owner.display_name} "
                f"({owner.alias}). Ask the user to pick another."
            )

    contact = Contact(
        alias=primary,
        name=new_name,
        phone=new_phone,
        digits=digits,
        email=new_email,
        aliases=tuple(new_aliases),
    )
    book[primary] = contact
    save_contacts(book, path)
    return contact


def remove_contact(
    who: str,
    *,
    path: Path | None = None,
) -> Contact | str:
    """Delete a contact by any nickname. Returns the removed Contact or an error."""
    path = path or CONTACTS_PATH
    book = load_contacts(path)
    contact = resolve_contact(who, book)
    if contact is None:
        return f"No contact matches {who!r}."
    del book[contact.alias]
    save_contacts(book, path)
    return contact
