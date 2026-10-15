"""One mistyped letter in a surname sent the email to the wrong person.

This is the file for item 3.8. SMS and email both turn a spoken name into a
person, and both had their own copy of the lookup. The copies were not equally
careful:

    spoken            sms resolved to     email resolved to
    "Sam Brightley"   brightley           brightley@example.com
    "Sam Brightly"    brightley           owner@example.com     <- the user

`resolve_sms_alias` had two guards that `resolve_email_address` did not. The
first tolerates a couple of edits in a last name, because "Brightley" and
"Brightly" are the same person and Whisper cannot tell which the user said.
The second refuses to let a multi-token name degrade into a bare first-name
match — "Sam Brightley" must never quietly become "sam", because a short alias
on somebody else's card will then answer to it.

Email had neither. "Brightly" missed every exact test, fell through to the
single-token loop, matched the first contact whose first name was "Sam", and
that was the owner's own card. The mail went to the user's own inbox. Nothing
failed: `EmailDraft.complete` only asks whether *an* address came back, so the
confirm card showed a real, familiar-looking address and read entirely
correctly. That is the worst shape a bug can have in this repo — a wrong
answer the user cannot see, rather than a refusal they can.

A third thing turned up while unifying them. `resolve_sms_alias` carried a
comment promising it prefers a real contact over the owner's own card when
several match a first name. It did not: `match_contact_label` matches on
substring and returned the owner first, so the preference below it was
unreachable. "text sam" texted you, with a Sam in the book.
"""

from __future__ import annotations

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.contact_match import find_contact
from arelis.core.email_complete import resolve_email_address
from arelis.core.sms_complete import resolve_sms_alias

OWNER_INBOX = "you@example.com"


@pytest.fixture(autouse=True)
def _owner_inbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the operator's real address out of these assertions.

    `_self_email` reads the live mail config, so "me" would otherwise resolve
    to whatever is in `data/secrets.yaml` on the machine running the suite.
    """
    monkeypatch.setattr("arelis.core.email_complete._self_email", lambda: OWNER_INBOX)


def _person(
    alias: str,
    name: str,
    phone: str,
    email: str = "",
    aliases: tuple[str, ...] = (),
) -> Contact:
    return Contact(
        alias=alias,
        name=name,
        phone=phone,
        digits=normalize_phone(phone),
        email=email,
        aliases=aliases,
    )


def _book() -> dict[str, Contact]:
    """Two people sharing a first name, one of whom is the owner.

    The collision is the fixture. Every bug in this file needed it, and no
    test in the suite had it before — which is why none of them caught any of
    this.
    """
    return {
        "me": _person("me", "Sam Rivers", "5555550100", OWNER_INBOX, aliases=("myself",)),
        "brightley": _person("brightley", "Sam Brightley", "5555550101", "brightley@example.com"),
        "hale": _person("hale", "Robin Hale", "5555550102", "hale@example.com"),
        "coach": _person("coach", "Dana Quill", "5555550103"),
    }


def test_saying_me_still_means_me() -> None:
    """The preference above must not have cost the owner their own card.

    "me" is an exact alias, so it never reaches the loose tier where the
    preference lives.
    """
    book = _book()
    assert resolve_sms_alias("me", book) == "me"
    assert resolve_sms_alias("myself", book) == "me"
    assert resolve_email_address("me", book) == OWNER_INBOX


def test_a_person_with_no_address_is_a_refusal_and_not_somebody_else() -> None:
    """The behaviour change this fix makes, and why it is the right one.

    The old first-name loop skipped contacts with no email and kept looking,
    so asking to mail someone unreachable could land on whoever else answered
    to their first name. Returning nothing is what makes `unresolved_named_to`
    true, which is what makes the preflight nudge ask for the address — the
    honest answer, and one already written.
    """
    book = _book()
    assert resolve_sms_alias("Dana Quill", book) == "coach"
    assert resolve_email_address("Dana Quill", book) == ""
    assert resolve_email_address("coach", book) == ""


def test_the_fuzzy_tolerance_stops_before_it_reaches_a_different_person() -> None:
    """Two edits, on the last token, with the first token exact.

    A free-text fuzzy match over a contact book is how you mail a stranger, so
    the tolerance is bounded on all three axes. "Sam Brightling" is three
    edits out and must miss; a different first name must miss however close
    the surname is.
    """
    book = _book()
    assert find_contact("Sam Brightling", book) is None
    assert find_contact("Dave Brightley", book) is None
    assert find_contact("Sam Brightly", book) is not None


