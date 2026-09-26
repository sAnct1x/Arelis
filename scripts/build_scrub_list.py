"""Build the local scrub list from your own records, without ever printing them.

`data/contacts.yaml` and `data/profile.yaml` are the definition of what counts as
personal in this project: names, nicknames, phone numbers, addresses, the city
you live in, the people you know. None of it may appear in a tracked file, because
tracked files become public the moment the repo is pushed.

Rather than keeping a list of forbidden words in a tracked test — which would put
the words themselves in the public repo, creating exactly the leak the test exists
to prevent — this script reads your real records and writes the terms to
`data/scrub-names.local.txt`. That path is under `data/`, which `.gitignore`
covers, so it never leaves this machine. `tests/test_no_personal_data.py` reads it
when it is there and skips the name checks when it is not.

Two consequences worth knowing. A contact you add next month is covered the next
time you run this, with no code change. And on CI, where the file does not exist,
the shape rules still run — which is correct, because the risk being defended
against is you or a tool on your machine reintroducing your own data, not a
stranger adding it.

Nothing here prints a name, a number or an address. The only output is a count.

    python scripts/build_scrub_list.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "data"

CONTACTS = DATA / "contacts.yaml"
PROFILE = DATA / "profile.yaml"
# Anyone who was never a contact: old handles, people you know but never text.
EXTRA = DATA / "scrub-extra.local.txt"
OUT = DATA / "scrub-names.local.txt"

# Relationship and role words are how contacts.yaml addresses people, and they
# are also ordinary English that appears throughout the codebase for good
# reasons. Scrubbing "wife" would flag the SMS parser on every line. A real
# nickname is not on this list and so is still caught.
GENERIC = frozenset(
    {
        "me", "myself", "my", "mine", "self", "owner", "user", "the user",
        "wife", "husband", "partner", "spouse", "mom", "mum", "mother", "dad",
        "father", "son", "daughter", "child", "kid", "brother", "sister",
        "sibling", "friend", "boss", "work", "home", "phone", "my phone",
        "mobile", "cell", "email", "e-mail", "mail", "primary", "default",
        "none", "null", "true", "false", "yes", "no", "unknown", "other",
        "contacts", "contact", "name", "aliases", "alias", "notes", "city",
        "state", "region", "country", "timezone", "units", "school", "pronouns",
    }
)

# Below this length a term matches half the codebase by accident.
MIN_LEN = 4

# A value carrying no letters at all: a coordinate, a postal code, a house
# number. These need separate handling because the digits-only transform below
# is built for phone numbers, where punctuation is arbitrary and stripping it is
# the whole point. Applied to a coordinate that transform destroys the term --
# 39.7817 becomes "397817", which appears in no file anywhere -- so the entry
# looked like coverage while providing none.
NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

# A bare integer shorter than this is a year, a port or a timeout. 2026 and 8765
# are both in this repo for honest reasons; a postal code is five.
MIN_BARE_INTEGER_DIGITS = 5

# Coordinates are kept down to two decimals, which is roughly a kilometre and
# the precision data/profile.example.yaml actually recommends, so a user who
# followed that advice is still covered. Below two, "42.1" would flag every
# version string in the tree.
MIN_COORD_DECIMALS = 2


def _scalars(node: Any) -> list[str]:
    """Every scalar in a nested structure, without needing to know the keys.

    Written as a walk rather than a list of fields on purpose: a field added to
    profile.yaml later is covered without anyone remembering to update this.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_scalars(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_scalars(value))
    elif node is not None and not isinstance(node, bool):
        found.append(str(node))
    return found


def _numeric_terms(text: str) -> set[str]:
    """Terms for a value with no letters in it, kept exactly as written.

    A fixture copies a coordinate the way it appears in the profile, so that is
    the form to look for. Truncated forms are emitted as well, because a pair
    pasted at four decimals and later rounded to three is the same doorstep, and
    the truncation is a prefix rather than a rounding so this can never invent a
    number that was not in the file it read.

    The sign is dropped, so a longitude is caught whether or not whoever copied
    it kept the minus.
    """
    out: set[str] = set()
    if not NUMERIC.fullmatch(text):
        return out
    whole, dot, frac = text.lstrip("+-").partition(".")
    if not dot:
        if len(whole) >= MIN_BARE_INTEGER_DIGITS:
            out.add(whole)
        return out
    # A fraction below one is a rate, a ratio or a threshold far more often than
    # it is a position, and "0.25" as a forbidden term would flag hundreds of
    # honest lines. The coverage given up is a coordinate within one degree of
    # the equator or the prime meridian.
    if whole == "0":
        return out
    for places in range(len(frac), MIN_COORD_DECIMALS - 1, -1):
        out.add(f"{whole}.{frac[:places]}")
    return out


def _terms_from(raw: str) -> set[str]:
    """A scalar becomes the whole value plus its parts.

    "Robin Hale" has to be caught as the full name, and also as "Robin" alone,
    because a fixture is far more likely to use the first name than both.
    Digits are emitted bare so a phone number matches however it was punctuated.
    A value that is only a number takes the opposite treatment in
    ``_numeric_terms``, since stripping punctuation out of a coordinate leaves a
    string no file will ever contain.
    """
    out: set[str] = set()
    text = raw.strip()
    if not text:
        return out

    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 7:
        out.add(digits)
        # Local form, so a number stored with a country code still matches a
        # fixture that wrote it without one.
        if len(digits) > 10:
            out.add(digits[-10:])

    if "@" in text:
        out.add(text.lower())
        out.add(text.split("@", 1)[0].lower())
        return out

    if not any(ch.isalpha() for ch in text):
        out |= _numeric_terms(text)
        return out

    out.add(text.lower())

    # Only a short, name-shaped value is broken into its words. profile.yaml has
    # free-text fields — how you like answers, what you do for work — and
    # splitting those contributed ordinary English like "daily" and "life" as
    # forbidden terms, which flagged 668 lines of innocent code the first time
    # this ran. A name, a city or a handle is one to three words with a capital
    # in it; a sentence is not.
    words = text.replace(",", " ").replace("/", " ").split()
    if len(words) > 3 or not any(word[:1].isupper() for word in words):
        return out

    for word in words:
        cleaned = word.strip(".,;:!?()[]\"'").lower()
        if cleaned:
            out.add(cleaned)
    return out


def collect() -> set[str]:
    terms: set[str] = set()

    for path in (CONTACTS, PROFILE):
        if not path.is_file():
            continue
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for scalar in _scalars(loaded):
            terms |= _terms_from(scalar)
        # Contact aliases are dict keys, not values, and a key is exactly the
        # nickname somebody would paste into a test.
        contacts = loaded.get("contacts") if isinstance(loaded, dict) else None
        if isinstance(contacts, dict):
            for key in contacts:
                terms |= _terms_from(str(key))

    if EXTRA.is_file():
        for line in EXTRA.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms |= _terms_from(line)

    return {
        term
        for term in terms
        if term not in GENERIC and (len(term) >= MIN_LEN or term.isdigit())
    }


def main() -> int:
    if not CONTACTS.is_file() and not PROFILE.is_file() and not EXTRA.is_file():
        print(
            "Nothing to read. Expected at least one of data/contacts.yaml, "
            "data/profile.yaml or data/scrub-extra.local.txt.",
            file=sys.stderr,
        )
        return 1

    terms = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "# Generated by scripts/build_scrub_list.py. Gitignored, never committed.\n"
        "# Terms that must not appear in any tracked file. Re-run after adding a\n"
        "# contact or editing your profile.\n"
        + "\n".join(sorted(terms))
        + "\n",
        encoding="utf-8",
    )
    # Deliberately a count. Printing the terms would put them in a terminal
    # buffer, a scrollback, and whatever log is watching this session.
    print(f"Wrote {len(terms)} terms to {OUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
