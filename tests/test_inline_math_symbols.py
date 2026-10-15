"""Inline $...$ in a chat reply must stay visible.

Single Greek symbols were flattened to unicode the desk face cannot draw,
so $\\theta$ and $\\Delta$ left a hole. A price closer was also reused as the
next opener, which glued "$1$, and $0$" into the raw fragment "$1, and0$"
and swallowed the formula after it.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont, QTextDocument

from arelis.mathtext import flatten_latex


@pytest.fixture(autouse=True)
def _qt(qt_app):
    from arelis.ui.math_images import begin_reply, clear_cache, wait_prewarm
    from arelis.ui.theme import load_fonts

    load_fonts()
    assert wait_prewarm(), "math warm-up did not finish"
    clear_cache()
    begin_reply()
    yield qt_app
    clear_cache()
    begin_reply()


def _html(src: str) -> str:
    from arelis.ui.markdown import render_markdown
    from arelis.ui.math_images import begin_reply, math_html

    begin_reply()
    return render_markdown(src, math=math_html)


def _doc(src: str) -> QTextDocument:
    doc = QTextDocument()
    font = QFont("Zen Kaku Gothic New")
    font.setPixelSize(22)
    # The desk face has no Greek. System fallback hides that on Linux.
    # The real window does not get that fallback for an application font.
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    doc.setDefaultFont(font)
    doc.setHtml(_html(src))
    return doc


def _math_image_names(doc: QTextDocument) -> list[str]:
    from PySide6.QtGui import QTextCursor

    names: list[str] = []
    cur = QTextCursor(doc)
    for pos in range(doc.characterCount() - 1):
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if cur.selectedText() != "\ufffc":
            continue
        fmt = cur.charFormat()
        if fmt.isImageFormat() and fmt.toImageFormat().name().startswith("arelis-math:"):
            names.append(fmt.toImageFormat().name())
    return names


def _fragment_draws(doc: QTextDocument, symbol: str) -> bool:
    """True when ``symbol`` is a real glyph, not the missing-glyph slot."""
    block = doc.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            frag = iterator.fragment()
            iterator += 1
            if symbol not in frag.text():
                continue
            layout_font = QFont(frag.charFormat().font())
            if not layout_font.family():
                layout_font = doc.defaultFont()
            layout_font.setPixelSize(22)
            layout_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
            from PySide6.QtGui import QTextLayout

            layout = QTextLayout(symbol, layout_font)
            layout.beginLayout()
            layout.createLine()
            layout.endLayout()
            runs = layout.lineAt(0).glyphRuns()
            if runs and all(index != 0 for run in runs for index in run.glyphIndexes()):
                return True
        block = block.next()
    return False


def _image_has_ink(name: str) -> bool:
    from PySide6.QtGui import QImage

    from arelis.ui.math_images import image_for_url

    image = image_for_url(name)
    if image is None or image.isNull() or image.width() < 2 or image.height() < 2:
        return False
    # A blank stand-in is 1x1. A drawn formula has opaque pixels.
    bits = image.convertToFormat(QImage.Format.Format_ARGB32)
    # Sample the buffer. Zero alpha means the symbol was dropped.
    w, h = bits.width(), bits.height()
    for y in range(0, h, max(1, h // 8)):
        for x in range(0, w, max(1, w // 8)):
            if bits.pixelColor(x, y).alpha() > 20:
                return True
    return False


def _symbol_visible(src: str, symbol: str) -> None:
    doc = _doc(src)
    names = _math_image_names(doc)
    if names and any(_image_has_ink(name) for name in names):
        return
    assert _fragment_draws(doc, symbol), src


def test_delta_inequality_keeps_the_symbol() -> None:
    src = r"$\Delta > 0$"
    doc = _doc(src)
    names = _math_image_names(doc)
    if names and any(_image_has_ink(name) for name in names):
        from arelis.ui.math_images import span_for_url

        span = span_for_url(names[0])
        assert span is not None
        assert "Delta" in span.tex and ">" in span.tex and "0" in span.tex
        return
    text = doc.toPlainText()
    assert "0" in text
    # The hole used to leave the relation and drop the symbol.
    assert text.strip() != "> 0"
    assert _fragment_draws(doc, "Δ")


def test_theta_in_a_sentence_stays_in_place() -> None:
    src = r"at $\theta$ = π"
    doc = _doc(src)
    text = doc.toPlainText()
    assert "at" in text
    assert "=" in text
    names = _math_image_names(doc)
    if names and any(_image_has_ink(name) for name in names):
        return
    assert "θ" in text
    assert _fragment_draws(doc, "θ")


def test_glued_price_fragment_is_not_shown_raw() -> None:
    """"$1$, and $0$" used to render as the raw fragment "$1, and0$"."""
    out = flatten_latex("$1, and0$")
    assert "$1, and0$" not in out
    assert "1" in out and "0" in out and "and" in out
    produced = flatten_latex("$1$, and $0$")
    assert "$1, and0$" not in produced
    assert "$" not in produced


def test_currency_stays_plain_text() -> None:
    src = "costs $5 and $10"
    assert flatten_latex(src) == src
    assert src in _doc(src).toPlainText()


def test_price_closer_does_not_swallow_the_next_formula() -> None:
    out = flatten_latex(r"It costs $1$, and $\theta$ is the angle")
    assert r"\theta" not in out
    assert "θ" in out
    assert "$1, and" not in out
    assert "$" not in out

    delta = flatten_latex(r"if $1$ and $\Delta > 0$ then")
    assert r"\Delta" not in delta
    assert "Δ" in delta
    assert "> 0" in delta or "Δ > 0" in delta
