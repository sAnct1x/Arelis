"""Who did they mean? One answer, for every channel that has to address someone.

`sms_complete` and `email_complete` both turn a spoken name into a person, and
both then project that person onto their own channel — SMS wants the book
*alias* (the phone is resolved later, by the tool), email wants the literal
address. The projection is genuinely different. The lookup was not, and having
it written twice cost a real bug:

    spoken            sms resolved to     email resolved to
    "Sam Brightley"   brightley           b@example.com
    "Sam Brightly"    brightley           you@example.com   ← the user

One mistyped letter in a surname, and the email went to a different person.
Not to a failure, not to a card saying "I don't have an address for them" — to
a valid-looking mailbox the user recognises, on a confirm card that reads
correctly, because `EmailDraft.complete` only asks whether *an* address was
found. The SMS side had been immune for a year: `_fuzzy_person_match` tolerates
two edits in a last name, and a multi-token name is never allowed to fall
through to a bare first-name match. Email had neither, so "Brightly" missed
every exact test and landed on the first contact whose first name was "Sam".

Both of those guards are in here now, and the name resolution is the same
question asked once.

The non-`me` preference is the third thing, and it had quietly stopped
working. `resolve_sms_alias` carries a comment saying it prefers a real
contact over the owner's own card when several match a first name — but
`match_contact_label` returns on a substring hit before that code is ever
reached, so "text sam" resolved to the owner while a Sam sat in the book. The
preference now applies across the whole loose tier, which is where it was
always meant to live: an exact alias still wins outright, and "me" still means
me.
"""

from __future__ import annotations

from arelis.contacts import Contact, match_contact_label, resolve_contact


def _clean(raw: str) -> str:
    return (raw or "").strip().rstrip(".,!;:")


def _edit_distance(a: str, b: str) -> int:
    """Small Levenshtein for last-name typos (Brightley ↔ Brightly)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _fuzzy_person_match(to: str, book: dict[str, Contact]) -> Contact | None:
    """Match multi-token names with a one/two-edit last-name tolerance.

    Bounded to the *last* token, and only when the first token is exact. A
    free-text fuzzy match over a contact book is how you mail a stranger.
    """
    parts = _clean(to).lower().split()
    if len(parts) < 2:
        return None
    first, last = parts[0], parts[-1]
    best: Contact | None = None
    best_dist = 99
    for contact in book.values():
        candidates = [contact.name, contact.alias, *contact.aliases]
        for cand in candidates:
            cparts = _clean(cand).lower().split()
            if len(cparts) < 2:
                continue
            if cparts[0] != first:
                continue
            dist = _edit_distance(last, cparts[-1])
            if dist <= 2 and dist < best_dist:
                best = contact
                best_dist = dist
    return best


def _prefer_not_me(hits: list[Contact]) -> Contact | None:
    """A loose match on a shared first name means the other person.

    Someone who meant themselves says "me", which is an exact alias and never
    reaches here. Someone who says a first name that happens to also be on the
    owner's own card means the contact.
    """
    if not hits:
        return None
    not_me = [c for c in hits if c.alias != "me"]
    return not_me[0] if not_me else hits[0]


def find_contact(name: str, book: dict[str, Contact]) -> Contact | None:
    """The person behind a spoken name, or None. Channel-agnostic.

    Three tiers, narrowest first, because the cost of a wrong answer here is a
    message delivered to someone who was never mentioned:

    1. An exact key — alias, nickname, title, or a number they typed.
    2. A multi-token name, matched whole and then with a fuzzy last name. It
       stops here either way: "Sam Brightley" must never degrade into "sam",
       which is how a short alias on another card steals a full name.
    3. A single token, matched loosely against labels and first names, with
       the owner's own card deprioritised.
    """
    cleaned = _clean(name)
    if not cleaned:
        return None

    hit = resolve_contact(name, book)
    if hit is not None:
        return hit

    parts = cleaned.split()
    if len(parts) >= 2:
        key = cleaned.lower()
        for contact in book.values():
            if _clean(contact.name).lower() == key:
                return contact
            if _clean(contact.alias).lower() == key:
                return contact
            if any(_clean(a).lower() == key for a in contact.aliases):
                return contact
        return _fuzzy_person_match(cleaned, book)

    labeled = match_contact_label(name, book)
    first = parts[0].lower()
    if len(first) < 2:
        return labeled

    hits: list[Contact] = [labeled] if labeled is not None else []
    for contact in book.values():
        if contact in hits:
            continue
        if first in contact.keys:
            hits.append(contact)
            continue
        name_first = (contact.name or "").split()[0].lower()
        if name_first and name_first == first:
            hits.append(contact)
    return _prefer_not_me(hits)
