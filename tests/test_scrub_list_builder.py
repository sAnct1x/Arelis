"""The generator that decides what counts as personal, tested for once.

`scripts/build_scrub_list.py` is the input to every name-based rule in
`tests/test_no_personal_data.py`. A term it fails to emit is a term nothing
downstream can ever catch, and the failure is silent in the worst way: the suite
stays green, the count it prints goes up, and the guard reports success while
looking for a string that exists in no file on earth.

That is not hypothetical. Every value in a profile shorter than seven digits --
which is every postal code and every coordinate written to four decimal places --
was dropped before reaching the list, and the comment in the function stated the
opposite, so a reader checking whether coordinates were covered was told yes.
Six tracked files carried a real city's coordinates at eleven-metre precision
past a guard that could not see them.

Every literal here is drawn from the declared fixture place in
`tests/test_no_personal_data.py`, because a test about not leaking coordinates
should not need its own.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_scrub_list.py"


def _load_builder():
    name = "build_scrub_list"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


BUILDER = _load_builder()


# ------------------------------------------------------- the coordinate defect


def test_a_coordinate_produces_a_term_a_file_could_actually_contain() -> None:
    """The whole defect in one assertion.

    A latitude of 39.7817 has six digits, so it fell under the seven-digit floor
    meant for phone numbers and produced nothing at all. The term has to be the
    number as written, because that is how it appears in the file that copied it.
    """
    terms = BUILDER._terms_from("39.7817")
    assert "39.7817" in terms


def test_a_coordinate_never_becomes_a_string_of_bare_digits() -> None:
    """The half-fix that would have looked like a fix.

    Lowering the digit floor alone would have emitted "397817", the phone-number
    form, which matches nothing: no file writes a latitude without its decimal
    point. The list would have grown, the count would have risen, and the
    coverage would still have been zero.
    """
    terms = BUILDER._terms_from("39.7817")
    assert "397817" not in terms
    assert all("." in term for term in terms)


def test_a_longitude_is_caught_without_its_minus_sign() -> None:
    """Whoever copies a coordinate into a fixture may drop the sign.

    The value is stored negative and may be pasted either way, so the term is
    the magnitude and the rule that consumes it treats a leading minus as a
    boundary rather than as part of the number.
    """
    terms = BUILDER._terms_from("-89.6501")
    assert "89.6501" in terms
    assert not any(term.startswith("-") for term in terms)


def test_a_coordinate_is_still_caught_after_somebody_rounds_it() -> None:
    """Two decimals is what profile.example.yaml actually recommends.

    A user who took that advice would have been protected by nothing if only the
    exact stored value were listed, and a fixture that rounds a borrowed pair is
    the same doorstep as the pair it was rounded from.
    """
    terms = BUILDER._terms_from("39.7817")
    assert {"39.7817", "39.781", "39.78"} <= terms


def test_every_shortened_coordinate_is_a_prefix_of_the_real_one() -> None:
    """Truncation, never rounding.

    Rounding would carry the last kept digit upward and so could emit a position
    that was in nobody's profile, which is both a false lead and a term able to
    flag an unrelated file. Every term must be a literal prefix of what was read,
    so the generator can only ever narrow what it was given, never invent.
    """
    source = "39.7817"
    for term in BUILDER._terms_from(source):
        assert source.startswith(term)


def test_a_fraction_below_one_is_not_mistaken_for_a_position() -> None:
    """A rate is not a place, and treating one as a place is unusable.

    "0.25" as a forbidden term would flag hundreds of honest lines of animation
    timing and threshold arithmetic, and a guard that cries wolf that loudly gets
    switched off. The cost is stated where the code makes the trade.
    """
    assert BUILDER._terms_from("0.25") == set()
    assert BUILDER._terms_from("0.9991") == set()


# ---------------------------------------------------------- the postal defect


def test_a_postal_code_produces_a_term() -> None:
    """Five digits, also below the phone floor, also silently dropped.

    A postal code is three or four thousand houses. It is not a phone number and
    it is not nothing.
    """
    assert "62701" in BUILDER._terms_from("62701")


def test_a_short_bare_integer_is_not_a_term() -> None:
    """The reason a floor exists at all.

    "2026" appears in dozens of date fixtures and 8765 is the inbound port. Any
    of them as a forbidden term would fail the suite on content that identifies
    nobody, which is how a privacy guard loses its authority.
    """
    assert BUILDER._terms_from("2026") == set()
    assert BUILDER._terms_from("8765") == set()


# ------------------------------------------- the paths that must keep working


def test_a_phone_number_still_becomes_its_bare_digits() -> None:
    """The behaviour the coordinate fix must not break.

    Punctuation in a phone number is arbitrary, so stripping it is correct there
    and only there. This is the case the seven-digit floor was written for.
    """
    terms = BUILDER._terms_from("+1 555-555-0123")
    assert "5555550123" in terms


def test_a_name_still_yields_itself_and_its_parts() -> None:
    """A fixture is likelier to use a first name than a full one."""
    terms = BUILDER._terms_from("Robin Hale")
    assert "robin hale" in terms
    assert "robin" in terms
    assert "hale" in terms


def test_a_sentence_is_not_broken_into_forbidden_words() -> None:
    """Free-text profile fields nearly made this tool useless.

    Splitting "how you like answers" into words contributed ordinary English to
    the forbidden list and flagged 668 innocent lines the first time it ran. Only
    a short, capitalised, name-shaped value is split.
    """
    terms = BUILDER._terms_from("short and plain; ask before assuming")
    assert "short" not in terms
    assert "before" not in terms
