"""Lone numbers in inline math, and an unbraced e^iθ exponent."""

from __future__ import annotations

import re
from html import unescape

from arelis.mathtext import flatten_for_render, flatten_latex
from arelis.ui.markdown import render_markdown
from arelis.ui.math_images import prepare_tex, wants_image


def _visible(src: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", render_markdown(src)))


def _drawn(src: str) -> str:
    raw: list[tuple[str, bool]] = []
    flatten_for_render(src, raw=raw)
    assert len(raw) == 1
    tex, display = raw[0]
    assert display is False
    assert wants_image(tex, display)
    return prepare_tex(tex)


def test_roots_show_the_numbers_without_dollars() -> None:
    src = "The roots are $1$, and $0$."
    out = flatten_latex(src)
    assert out == "The roots are 1, and 0."
    assert "$" not in out
    visible = _visible(src)
    assert visible == "The roots are 1, and 0."
    assert "$" not in visible


def test_named_values_drop_the_dollars() -> None:
    src = "Set $x$ to $2$ and $y$ to $10$."
    out = flatten_latex(src)
    assert out == "Set x to 2 and y to 10."
    assert "$" not in out
    visible = _visible(src)
    assert visible == "Set x to 2 and y to 10."
    assert "$" not in visible


def test_prices_keep_their_dollar() -> None:
    costs = "It costs $5 and $10."
    assert flatten_latex(costs) == costs
    assert "$5" in render_markdown(costs)
    mixed = r"cost is $5 and $\log x$ stays math"
    out = flatten_latex(mixed)
    assert "$5" in out
    assert "log" in out
    assert r"\log" not in out


def test_glued_price_fragment_is_numbers_only() -> None:
    out = flatten_latex("$1, and0$")
    assert out == "1, and 0"
    assert "$" not in out
    assert "$" not in render_markdown("$1, and0$")


def test_space_around_a_number_stays_text() -> None:
    src = "The count is $ 1 $ today."
    out = flatten_latex(src)
    assert out == src
    assert "$" in out


def test_signed_and_grouped_numbers_drop_the_dollars() -> None:
    out = flatten_latex("Shift by $-3$, keep $2.5$, about $1,000$.")
    assert out == "Shift by -3, keep 2.5, about 1,000."
    assert "$" not in out


def test_euler_unbraced_theta_joins_the_exponent() -> None:
    braced = _drawn(r"The identity is $e^{i\theta}$.")
    word = _drawn("Euler's formula is $e^iθ$.")
    command = _drawn(r"Euler's formula is $e^i\theta$.")
    assert word == braced
    assert command == braced
    assert r"^{i\theta}" in braced
    for src in ("Euler's formula is $e^iθ$.", r"Euler's formula is $e^i\theta$."):
        plain = flatten_latex(src)
        assert "ⁱ" not in plain
        assert "θ" in plain
        html = render_markdown(src)
        assert "ⁱ" not in html


def test_space_before_theta_does_not_join_the_exponent() -> None:
    src = r"Written as $e^i \theta$ on purpose."
    raw: list[tuple[str, bool]] = []
    flatten_for_render(src, raw=raw)
    assert len(raw) == 1
    tex, display = raw[0]
    assert display is False
    assert prepare_tex(tex) == r"e^i \theta"
    assert wants_image(tex, display)
