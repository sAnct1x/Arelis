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


def test_a_surname_typo_does_not_mail_the_user_their_own_draft() -> None:
    """The defect, stated as plainly as it can be.

    One character. The address that came back was valid, was the user's own,
    and looked right on the card.
    """
    assert resolve_email_address("Sam Brightly", _book()) == "brightley@example.com", (
        "A one-edit surname typo resolved to something other than Sam "
        "Brightley. If this is the owner's inbox, the 3.8 defect is back."
    )
    assert resolve_email_address("Sam Brightly", _book()) != OWNER_INBOX


@pytest.mark.parametrize(
    "spoken",
    ["Sam Brightley", "Sam Brightly", "sam brightlee", "SAM BRIGHTLEY", "Sam Brightley."],
)
def test_the_two_channels_agree_on_who_a_spoken_name_is(spoken: str) -> None:
    """The actual unification claim, tested as a claim about agreement.

    Not "both return something" — both return *the same person*. The alias and
    the address are different projections of one answer, so the test compares
    them through the book.
    """
    book = _book()
    alias = resolve_sms_alias(spoken, book)
    address = resolve_email_address(spoken, book)
    assert alias == "brightley", spoken
    assert address == book[alias].email, (
        f"{spoken!r} is {alias} to SMS and {address} to email. These are the "
        "same lookup and must not answer differently."
    )


def test_a_first_name_the_owner_also_answers_to_means_the_other_person() -> None:
    """The unreachable preference, now reachable.

    `resolve_sms_alias` always said it did this. `match_contact_label` matched
    "sam" against "sam rivers" by substring and returned the owner before the
    code implementing the promise ever ran.
    """
    book = _book()
    assert resolve_sms_alias("sam", book) == "brightley", (
        "Texting 'sam' resolved to the owner's own card while a Sam was in "
        "the book. The non-me preference is unreachable again."
    )
    assert resolve_email_address("sam", book) == "brightley@example.com"


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


def test_a_name_nobody_in_the_book_answers_to_resolves_to_nothing() -> None:
    """Inventing a recipient is worse than admitting there isn't one."""
    book = _book()
    assert resolve_sms_alias("Nobody Atall", book) == ""
    assert resolve_email_address("Nobody Atall", book) == ""


def test_a_literal_address_is_used_as_given_without_consulting_the_book() -> None:
    assert resolve_email_address("bob@example.com", _book()) == "bob@example.com"


def test_a_full_name_never_degrades_into_a_bare_first_name_match() -> None:
    """The guard SMS had and email did not, tested where it bites.

    With no Brightley in the book at all, "Sam Brightley" has to come back
    empty rather than finding the owner because they are also a Sam. A
    two-token name is a more specific request, and answering it with a
    one-token match is how a message reaches a stranger.
    """
    book = {
        "me": _person("me", "Sam Rivers", "5555550100", OWNER_INBOX),
        "hale": _person("hale", "Robin Hale", "5555550102", "hale@example.com"),
    }
    assert resolve_sms_alias("Sam Brightley", book) == ""
    assert resolve_email_address("Sam Brightley", book) == ""


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


def test_an_exact_alias_beats_every_looser_reading_of_it() -> None:
    """Tier order. A nickname the user set is not a guess and outranks one."""
    book = _book()
    book["sam"] = _person("sam", "Samantha Reed", "5555550104", "reed@example.com")
    assert resolve_sms_alias("sam", book) == "sam"
    assert resolve_email_address("sam", book) == "reed@example.com"


def test_a_leading_my_is_dropped_the_same_way_on_both_channels() -> None:
    book = _book()
    book["wife"] = _person("wife", "Robin Hale", "5555550102", "hale@example.com")
    assert resolve_sms_alias("my wife", book) == "wife"
    assert resolve_email_address("my wife", book) == "hale@example.com"


def test_an_empty_name_asks_for_nobody_on_sms_and_means_the_owner_on_email() -> None:
    """A real difference between the channels, and a deliberate one.

    An empty `to` on email is the "email myself this" case and has a sensible
    answer. On SMS it is nothing at all — there is no default number, and
    guessing one would be a message to whoever sorts first.
    """
    book = _book()
    assert resolve_sms_alias("", book) == ""
    assert resolve_email_address("", book) == OWNER_INBOX
    assert find_contact("", book) is None


def test_a_number_the_user_typed_finds_the_person_it_belongs_to() -> None:
    book = _book()
    assert resolve_sms_alias("5555550101", book) == "brightley"


def test_the_first_name_tier_has_a_floor_but_the_label_tier_does_not() -> None:
    """Pinned as found, not as wanted. The looseness is not in this lane.

    `find_contact`'s own first-name scan refuses a single character, because
    "s" is not a request for Sam. But the tier above it calls
    `contacts.match_contact_label`, which matches on substring in *either*
    direction with only a three-character floor on the stored name — so `cand
    in name` makes a one-letter query match anybody whose name contains that
    letter. "s" comes back as Sam Rivers.

    That function was written to match Google Messages notification titles,
    where a loose substring match is the right call, and it is reused here for
    spoken names, where it is not. Fixing it means editing `arelis/contacts.py`,
    which this lane may not touch, and putting a length floor in `find_contact`
    instead would change SMS resolution on no evidence. So the behaviour is
    recorded here and reported instead of changed.

    If someone tightens `match_contact_label`, this test is the one that will
    fail, and the right response is to flip it rather than restore the
    looseness.
    """
    book = _book()
    assert find_contact("s", book) is not None
    # Two characters is enough to reach the first-name tier, which is stricter:
    # it wants a real first-name or alias equality, not a substring.
    assert find_contact("zz", book) is None
