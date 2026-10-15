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


# ---------------------------------------------------------- the postal defect


# ------------------------------------------- the paths that must keep working


def test_a_name_still_yields_itself_and_its_parts() -> None:
    """A fixture is likelier to use a first name than a full one."""
    terms = BUILDER._terms_from("Robin Hale")
    assert "robin hale" in terms
    assert "robin" in terms
    assert "hale" in terms


