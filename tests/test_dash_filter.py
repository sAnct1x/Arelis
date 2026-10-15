"""Dash filter: model prose never paints an em dash; streaming stays coherent.

Catches the habit the persona rule alone cannot kill on a small model.
"""

from __future__ import annotations

import random
import re

import pytest

EM = "\u2014"
EN = "\u2013"
HB = "\u2015"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(f'It works {EM} I tested it.', 'It works, I tested it.'), (f'It works{EM}I tested it.', 'It works, I tested it.')],
)
def test_clean_dashes_table(raw: str, expected: str) -> None:
    from arelis.core.dash_filter import clean_dashes

    assert clean_dashes(raw) == expected


def test_no_double_comma_double_space_or_leading_comma() -> None:
    from arelis.core.dash_filter import clean_dashes

    samples = [
        f"so, {EM} then",
        f"  {EM} leading",
        f"end {EM}  ",
        f"a {EM}  b",
        f"hi {EM}.",
    ]
    for raw in samples:
        got = clean_dashes(raw)
        assert ", ," not in got
        assert "  " not in got.replace("\n", "")
        assert not got.startswith(",")
        assert ",." not in got
        assert ",?" not in got


def test_property_chunking_seeded() -> None:
    from arelis.core.dash_filter import DashFilter, clean_dashes

    alphabet = " a1\n," + EM + EN
    rnd = random.Random(42)
    for _ in range(200):
        n = rnd.randint(0, 40)
        s = "".join(rnd.choice(alphabet) for _ in range(n))
        expected = clean_dashes(s)
        cuts = sorted(rnd.sample(range(len(s) + 1), k=min(len(s) + 1, rnd.randint(1, 5))))
        parts = [s[a:b] for a, b in zip([0, *cuts], [*cuts, len(s)], strict=True)]
        filt = DashFilter()
        got = "".join(filt.feed(p) for p in parts) + filt.flush()
        assert got == expected
        assert clean_dashes(got) == got
        # Em and horizontal bar never survive outside code (no backticks here).
        assert EM not in got
        assert HB not in got
        # Any surviving en dash must sit in a digit range (spaces ok).
        for m in re.finditer(EN, got):
            i = m.start()
            left = got[:i].rstrip(" \t")
            right = got[i + 1 :].lstrip(" \t")
            assert left.endswith(tuple("0123456789"))
            assert right[:1].isdigit()


LDQ = "\u201c"
RDQ = "\u201d"
LSQ = "\u2018"
RSQ = "\u2019"


