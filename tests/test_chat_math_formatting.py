"""Chat math stays readable: symbols, stars, pipes, minus signs, list numbers."""

from __future__ import annotations

import pytest

from arelis.core.dash_filter import DashFilter, clean_dashes
from arelis.ui.markdown import render_markdown

_EM = "\u2014"
_EN = "\u2013"


@pytest.fixture(autouse=True)
def _qt(qt_app):
    """Offscreen app from conftest, before any document is built."""
    return qt_app


def _blocks(src: str) -> list[str]:
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setHtml(render_markdown(src))
    out: list[str] = []
    block = doc.begin()
    while block.isValid():
        listing = block.textList()
        prefix = (listing.itemText(block) + " ") if listing else ""
        out.append(prefix + block.text())
        block = block.next()
    return [line for line in out if line.strip()]


def _vis(src: str) -> str:
    return " | ".join(_blocks(src))


@pytest.mark.parametrize(
    ("src", "want"),
    [
        (r"$A \cup B$", "\u222a"),
        (r"$A \cap B$", "\u2229"),
        (r"$\langle v, w \rangle$", "\u27e8"),
        (r"$p \implies q$", "\u21d2"),
        (r"$x \perp y$", "\u22a5"),
    ],
)
def test_known_symbols_are_not_deleted(src: str, want: str) -> None:
    assert want in _vis(src)


def test_unknown_command_is_never_silently_dropped() -> None:
    assert "xyz" in _vis(r"$a \xyz b$")


def test_asterisk_multiplication_survives_inside_math() -> None:
    visible = _vis(r"Area is $a * b * c$ units.")
    assert "a * b * c" in visible or "a \u00d7 b \u00d7 c" in visible


def test_digit_led_inline_math_is_flattened() -> None:
    visible = _vis(r"Solve $2x^2 + 3x - 5 = 0$ for x.")
    assert "$" not in visible and "x\u00b2" in visible


def test_spaced_inline_math_is_flattened() -> None:
    visible = _vis(r"Let $ x_n \to 0 $ as n grows.")
    assert "$" not in visible and "x\u2099" in visible


def test_inline_parens_may_span_a_newline() -> None:
    assert "\\(" not in _vis("We get \\(x =\n\\frac{-b}{2a}\\) here.")


def test_pipe_inside_math_does_not_split_table_cell() -> None:
    rows = _blocks("| f | value |\n|---|---|\n| abs | $|x|$ |")
    assert any("|x|" in row for row in rows)


def test_ordered_list_keeps_its_start_number() -> None:
    assert _blocks("3. third\n4. fourth")[0].startswith("3.")


def test_display_math_in_list_does_not_restart_numbering() -> None:
    rows = _blocks("1. First $$x = 2$$\n2. Second\n3. Third")
    assert any(row.startswith("2. Second") for row in rows)


@pytest.mark.parametrize(
    ("src", "bad"),
    [
        ("So x = \u20133.", "=,"),
        ("(x \u2013 1)", "(x,"),
    ],
)
def test_dash_filter_keeps_minus_in_math(src: str, bad: str) -> None:
    assert bad not in clean_dashes(src)


def test_line_start_negative_number_is_not_a_bullet() -> None:
    assert _blocks(clean_dashes("\u20135 is the answer."))[0].startswith(("-5", "\u22125"))


@pytest.mark.parametrize(
    "src",
    [
        "$5",
        "$10",
        "costs $5 and $10",
        "$5 to $10",
        "$1,200.50",
        "between $3 and $4 each",
    ],
)
def test_prices_stay_unchanged(src: str) -> None:
    assert src in _vis(src)


def test_backslash_star_outside_math_is_literal() -> None:
    assert "a * b * c" in _vis(r"a \* b \* c")


def test_spaced_single_name_is_flattened() -> None:
    visible = _vis("Value is $ x $ here.")
    assert "$" not in visible
    assert "x" in visible


def test_prose_dashes_are_still_cleaned() -> None:
    raw = f"This is the plan {_EM} short and simple {_EN} nothing more."
    got = clean_dashes(raw)
    assert _EM not in got
    assert _EN not in got
    assert got == "This is the plan, short and simple, nothing more."


def test_prose_dash_split_across_chunks_still_cleans() -> None:
    raw = f"This is the plan {_EM} short and simple."
    cut = raw.index(_EM)
    parts = [raw[:cut], raw[cut : cut + 1], raw[cut + 1 :]]
    filt = DashFilter()
    streamed = "".join(filt.feed(part) for part in parts) + filt.flush()
    assert streamed == clean_dashes(raw)
    assert _EM not in streamed
    assert "plan, short" in streamed
