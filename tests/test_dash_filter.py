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


def test_module_importable() -> None:
    from arelis.core.dash_filter import DashFilter, clean_dashes

    assert callable(clean_dashes)
    assert DashFilter is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"It works {EM} I tested it.", "It works, I tested it."),
        (f"It works{EM}I tested it.", "It works, I tested it."),
        (f"yes{EM}no", "yes, no"),
        (f"a {EN} b", "a, b"),
        (f"Pages 3{EN}5 and 2020{EN}2024", f"Pages 3{EN}5 and 2020{EN}2024"),
        (f"5{EN}10", f"5{EN}10"),
        (f"3 {EN} 5", f"3 {EN} 5"),
        (f"Navier{EN}Stokes", "Navier-Stokes"),
        (f"wait {EM}\nnext", "wait\nnext"),
        (f"{EM} item\n{EM}\n", "- item\n-\n"),
        (f"| a | {EM} |", "| a | - |"),
        (f'say "{EM} hi"', 'say "hi"'),
        (f"so, {EM} then", "so, then"),
        (f"wait {EM}.", "wait."),
        (f"wait {EM}?", "wait?"),
        ("`a " + EM + " b`", "`a " + EM + " b`"),
        (
            "```py\nx = 1 " + EM + " 2\n```\nthen " + EM + " after",
            "```py\nx = 1 " + EM + " 2\n```\nthen, after",
        ),
        (
            "> quote " + EM + " cleaned\nnext " + EM + " gone",
            "> quote, cleaned\nnext, gone",
        ),
        (f"X {EM} y {EM} z", "X, y, z"),
        (f"A{EM}{EM}B", "A, B"),
        ("你好" + EM + EM + "世界", "你好\uff0c世界"),
        ("no dash here", "no dash here"),
        (f"trailing {EM}", "trailing"),
        (f"{EM}", "-"),
        (f"see https://example.com/a{EM}b and done {EM} ok", f"see https://example.com/a{EM}b and done, ok"),
        (f"see http://x.test/p{EM}q then {EM} end", f"see http://x.test/p{EM}q then, end"),
        (f"spaced {HB} bar", "spaced, bar"),
    ],
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


def test_blockquote_prose_is_cleaned() -> None:
    from arelis.core.dash_filter import DashFilter, clean_dashes

    raw = "> she said " + EM + " then left\nnext " + EM + " gone"
    expected = "> she said, then left\nnext, gone"
    assert clean_dashes(raw) == expected
    assert EM not in clean_dashes(raw)
    # Nested quote marker, URL and inline code still exempt.
    mixed = (
        ">> cite " + EM + " here and `keep " + EM + " this` "
        "see https://ex.test/a" + EM + "b done " + EM + " ok"
    )
    got = clean_dashes(mixed)
    assert got.startswith(">> cite, here")
    assert "`keep " + EM + " this`" in got
    assert "https://ex.test/a" + EM + "b" in got
    assert EM not in got.replace("`keep " + EM + " this`", "").replace(
        "https://ex.test/a" + EM + "b", ""
    )
    parts = ["> quote ", EM, " then\nplain ", EM, " x"]
    filt = DashFilter()
    streamed = "".join(filt.feed(p) for p in parts) + filt.flush()
    assert streamed == clean_dashes("".join(parts))
    assert streamed == "> quote, then\nplain, x"


def test_sms_and_email_bodies_cleaned() -> None:
    from arelis.core.dash_filter import clean_dashes

    sms = f"Hey {EM} running late"
    email_body = f"Hi,\n\nQuick note {EM} see you at 5.\n"
    subject = f"Dinner {EM} Tuesday"
    assert clean_dashes(sms) == "Hey, running late"
    assert clean_dashes(email_body) == "Hi,\n\nQuick note, see you at 5.\n"
    assert clean_dashes(subject) == "Dinner, Tuesday"


def test_prepare_body_strips_em_dash() -> None:
    from arelis.sms import prepare_body

    body, truncated = prepare_body(f"Hey {EM} running late")
    assert not truncated
    assert body == "Hey, running late"
    assert EM not in body


@pytest.mark.parametrize(
    "parts",
    [
        ["word ", EM, " next"],
        ["word", " ", EM, "next"],
        ["word " + EM, " next"],
        ["word", " " + EM + " ", "next"],
        [f"a{EM}", "b"],
        ["Sure ", EM, " here", " you go."],
        ["wait ", EM],
    ],
)
def test_streaming_splits_match_whole(parts: list[str]) -> None:
    from arelis.core.dash_filter import DashFilter, clean_dashes

    whole = "".join(parts)
    filt = DashFilter()
    got = "".join(filt.feed(p) for p in parts) + filt.flush()
    assert got == clean_dashes(whole)


def test_chunk_invariance_and_char_by_char() -> None:
    from arelis.core.dash_filter import DashFilter, clean_dashes

    cases = [
        f"It works {EM} I tested it.",
        f"yes{EM}no",
        f"a {EN} b",
        f"Pages 3{EN}5",
        "```py\nx = 1 " + EM + " 2\n```\nthen " + EM + " after",
        "`code " + EM + " x`",
        f"see https://example.com/a{EM}b then {EM} ok",
        f"trailing {EM}",
    ]
    rnd = random.Random(1)
    for s in cases:
        expected = clean_dashes(s)
        filt = DashFilter()
        by_char = "".join(filt.feed(c) for c in s) + filt.flush()
        assert by_char == expected
        for _ in range(40):
            cuts = sorted(
                rnd.sample(range(len(s) + 1), k=min(len(s) + 1, rnd.randint(0, 6)))
            )
            parts = [s[a:b] for a, b in zip([0, *cuts], [*cuts, len(s)], strict=True)]
            filt = DashFilter()
            got = "".join(filt.feed(p) for p in parts) + filt.flush()
            assert got == expected


def test_hold_bound_after_plain_word_and_trailing_space() -> None:
    from arelis.core.dash_filter import DashFilter

    filt = DashFilter()
    assert filt.feed("word") == "word"
    filt = DashFilter()
    out = filt.feed("word ")
    assert out in {"word", "word "}
    assert "word" in out
    # Held tail is at most trailing spaces (plus a later unresolved dash).
    held_estimate = len("word ") - len(out)
    assert held_estimate <= 1


def test_idempotent_and_no_em_outside_code() -> None:
    from arelis.core.dash_filter import clean_dashes

    samples = [
        f"It works {EM} I tested it.",
        f"a {EN} b",
        f"Pages 3{EN}5 stay",
        "```\n" + EM + "\n```\nout " + EM + " x",
    ]
    for s in samples:
        once = clean_dashes(s)
        assert clean_dashes(once) == once
    prose = clean_dashes(f"Hello {EM} world")
    assert EM not in prose
    assert HB not in prose


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f'He said {EM} "stop"', 'He said, "stop"'),
        (f"frame {EM} '2.7 K to the CMB frame' is a Doppler boost",
         "frame, '2.7 K to the CMB frame' is a Doppler boost"),
        (f"He said {EM} {LDQ}stop{RDQ}", f"He said, {LDQ}stop{RDQ}"),
        (f"He said {EM} {LSQ}stop{RSQ}", f"He said, {LSQ}stop{RSQ}"),
        (f'so, {EM} "then"', 'so, "then"'),
        (f'word{EM}"end"', 'word"end"'),
        (f"word{EM}'end'", "word'end'"),
        (f"hello{EM}{RDQ}", f"hello{RDQ}"),
        (f"hello{EM}{RSQ}", f"hello{RSQ}"),
    ],
)
def test_spaced_dash_before_opening_quote(raw: str, expected: str) -> None:
    from arelis.core.dash_filter import clean_dashes

    assert clean_dashes(raw) == expected


@pytest.mark.parametrize(
    "parts",
    [
        ["He said ", EM, ' "stop"'],
        ["He said " + EM, ' "stop"'],
        ['He said ' + EM + " ", '"stop"'],
        ["He said", f" {EM} ", '"stop"'],
        ["frame ", EM, " '2.7 K'"],
        ["frame " + EM + " ", "'2.7 K'"],
        ["He said ", EM, f" {LDQ}stop{RDQ}"],
        ["He said ", EM, f" {LSQ}stop{RSQ}"],
    ],
)
def test_quote_after_dash_survives_stream_splits(parts: list[str]) -> None:
    from arelis.core.dash_filter import DashFilter, clean_dashes

    whole = "".join(parts)
    filt = DashFilter()
    got = "".join(filt.feed(p) for p in parts) + filt.flush()
    assert got == clean_dashes(whole)
    assert 'said"stop' not in got
    assert "frame'" not in got or "frame, '" in got or "frame '" in got
