"""Fill non-secret fields from contacts.yaml. No street address. No memory."""

from __future__ import annotations

from typing import Any

from arelis.contacts import Contact, load_contacts, resolve_contact

# Contact slots the model may name. Address is not one of them.
_FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("work_phone", ("work phone", "work_phone", "office phone", "office")),
    ("email", ("email", "e-mail", "e mail", "mail")),
    ("phone", ("phone", "mobile", "cell", "tel", "telephone", "sms")),
    ("name", ("name", "full name", "first name", "your name")),
)
_ADDRESS = (
    "address",
    "street",
    "city",
    "zip",
    "postal",
    "apt",
    "apartment",
)


def contact_field_for(into: str) -> str:
    """Which contact slot ``into`` names, or ''."""
    needle = " ".join(str(into or "").split()).casefold()
    if not needle:
        return ""
    for field, aliases in _FIELD_ALIASES:
        if any(alias in needle for alias in aliases):
            return field
    return ""


def is_address_into(into: str) -> bool:
    needle = " ".join(str(into or "").split()).casefold()
    return bool(needle) and any(word in needle for word in _ADDRESS)


def contact_value(contact: Contact, field: str) -> str:
    if field == "name":
        return (contact.name or contact.display_name or "").strip()
    if field == "email":
        return (contact.email or "").strip()
    if field == "phone":
        return (contact.phone or "").strip()
    if field == "work_phone":
        return (contact.work_phone or "").strip()
    return ""


def fill_from_who(
    who: str,
    *,
    into: str = "",
    contacts: dict[str, Contact] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return ``(value, data)``. ``data['error']`` is set on failure."""
    label = str(who or "").strip()
    data: dict[str, Any] = {"who": label}
    if not label:
        data["error"] = "who= needs a contact name."
        return "", data
    if is_address_into(into):
        data["error"] = (
            "Contact has no street address. "
            "who= fills name, phone, email, or work_phone only."
        )
        data["code"] = "NO_ADDRESS"
        return "", data
    field = contact_field_for(into)
    if not field:
        data["error"] = (
            "who= needs into=name, into=phone, into=email, or into=work_phone."
        )
        data["code"] = "WHO_FIELD"
        return "", data
    book = contacts if contacts is not None else load_contacts()
    contact = resolve_contact(label, book)
    if contact is None:
        data["error"] = f"No contact matching {label!r} in contacts.yaml."
        data["code"] = "NO_CONTACT"
        return "", data
    value = contact_value(contact, field)
    data["field"] = field
    data["contact"] = contact.alias
    if not value:
        data["error"] = (
            f"{contact.display_name} has no {field} in contacts.yaml."
        )
        data["code"] = "EMPTY_FIELD"
        return "", data
    return value, data
