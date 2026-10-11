"""Math images in chat.

The eleven behaviour tests failed on main before formulas were drawn. The four
guard tests passed there and still must. Offscreen, same app as the rest of
the suite.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _qt(qt_app):
    return qt_app

FRAC = r"\frac{a}{b}"
SUM = r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}"
PMATRIX = r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}"


def _panel():
    from arelis.ui.panels.chat import ChatPanel

    p = ChatPanel()
    p.resize(640, 480)
    return p


def _reply(panel, text: str, *, deltas: list[str] | None = None) -> None:
    panel.begin_assistant()
    for d in deltas or [text]:
        panel.append_delta(d)
    panel.finish_assistant(text)


def _math_images(doc) -> list:
    """Every image in the document whose name uses the math scheme."""
    out = []
    cur = QTextCursor(doc)
    for pos in range(doc.characterCount() - 1):
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if cur.selectedText() != "\ufffc":
            continue
        fmt = cur.charFormat()
        if fmt.isImageFormat() and fmt.toImageFormat().name().startswith("arelis-math:"):
            out.append(fmt.toImageFormat())
    return out


def _resource(view, fmt) -> QImage:
    res = view.document().resource(QTextDocument.ResourceType.ImageResource, QUrl(fmt.name()))
    if res is None:
        res = view.loadResource(int(QTextDocument.ResourceType.ImageResource.value), QUrl(fmt.name()))
    return res.toImage() if hasattr(res, "toImage") else res


# ---------------------------------------------------------------- FAILFIRST


def test_fraction_reply_shows_a_rendered_fraction_image_not_raw_text():
    """FAILFIRST. Main flattens to Unicode text (no image)."""
    p = _panel()
    _reply(p, f"The ratio is ${FRAC}$ here.")
    imgs = _math_images(p.view.document())
    assert len(imgs) == 1
    text = p.view.toPlainText()
    assert "\\frac" not in text and "a/b" not in text and "(a)/(b)" not in text


def test_display_sum_is_one_image_whose_alt_is_the_latex():
    """FAILFIRST. Accessibility and Ctrl+F hook: alt (and tooltip) carry the source."""
    p = _panel()
    _reply(p, f"$${SUM}$$")
    imgs = _math_images(p.view.document())
    assert len(imgs) == 1
    alt = imgs[0].stringProperty(QTextFormat.Property.ImageAltText)
    assert alt == SUM and imgs[0].toolTip() == SUM


def test_copying_a_formula_gives_its_latex():
    """FAILFIRST. Main copies the Unicode flattening; a naive image copy gives U+FFFC."""
    p = _panel()
    _reply(p, f"Area is ${FRAC}$ units.")
    p.view.selectAll()
    text = p.view.createMimeDataFromSelection().text()
    assert f"${FRAC}$" in text and "\ufffc" not in text


def test_a_formula_that_cannot_render_falls_back_to_readable_unicode():
    """FAILFIRST (via the first assert). pmatrix is outside mathtext; the reply still shows
    the fraction as an image and the matrix as Unicode text, never raw TeX or an empty box."""
    p = _panel()
    _reply(p, f"First ${FRAC}$ then $${PMATRIX}$$")
    assert len(_math_images(p.view.document())) == 1
    text = p.view.toPlainText()
    assert "\\begin" not in text and "pmatrix" not in text
    assert "1" in text and "4" in text


def test_formulas_match_the_theme_text_colour_and_follow_a_theme_switch():
    """FAILFIRST. Ink equals COLORS['text']; switching theme repaints without new HTML."""
    from arelis.ui.theme import COLORS, apply_theme

    def ink(view):
        fmt = _math_images(view.document())[0]
        img = _resource(view, fmt).convertToFormat(QImage.Format.Format_RGBA8888)
        a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.width(), 4)
        solid = a[a[..., 3] > 230][:, :3]
        return np.median(solid, axis=0)

    def hexrgb(h):
        return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)])

    try:
        apply_theme("night")
        p = _panel()
        _reply(p, f"${FRAC}$")
        assert np.abs(ink(p.view) - hexrgb(COLORS["text"])).max() <= 8
        apply_theme("sodium")
        p.refresh_bubble_wash()
        assert np.abs(ink(p.view) - hexrgb(COLORS["text"])).max() <= 8
    finally:
        apply_theme("sodium")


def test_formula_image_is_crisp_on_hidpi():
    """FAILFIRST. Rendered at 2x or more with devicePixelRatio set, so it lays out at logical size."""
    p = _panel()
    _reply(p, f"${FRAC}$")
    img = _resource(p.view, _math_images(p.view.document())[0])
    assert img.devicePixelRatio() >= 2.0


def test_streaming_shows_raw_tex_then_an_image_on_finish():
    """FAILFIRST (second half). No images mid-stream (a half-open $ must never render)."""
    p = _panel()
    p.begin_assistant()
    p.append_delta("so $")
    p.append_delta(FRAC + "$")
    assert _math_images(p.view.document()) == []
    p.finish_assistant(f"so ${FRAC}$")
    assert len(_math_images(p.view.document())) == 1


def test_chat_text_scale_rerenders_formulas_larger():
    """FAILFIRST. Ctrl+= grows formulas with the body text."""
    p = _panel()
    _reply(p, f"${FRAC}$")
    fmt = _math_images(p.view.document())[0]
    before = _resource(p.view, fmt).deviceIndependentSize().height()
    p.set_text_scale(1.5)
    after = _resource(p.view, _math_images(p.view.document())[0]).deviceIndependentSize().height()
    assert after > before * 1.3


def test_history_reload_renders_formula_images():
    """FAILFIRST. load_messages goes through setHtml; resources must survive view.clear()."""
    p = _panel()
    p.load_messages([{"role": "user", "content": "ratio?"}, {"role": "assistant", "content": f"${FRAC}$"}])
    assert len(_math_images(p.view.document())) == 1


def test_inline_formula_sits_on_the_text_baseline():
    """FAILFIRST. Within 1 px of the text baseline (vertical-align:middle plus padding)."""
    p = _panel()
    _reply(p, r"xx $x_n^2$")
    fmt = _math_images(p.view.document())[0]
    assert fmt.verticalAlignment().name in {"AlignMiddle", "AlignBaseline"}
    # pixel check lives in math-images-data/proto_baseline.py; port it with the fix


def test_chart_image_rides_the_same_resource_hook():
    """FAILFIRST. Data-tool charts: a registered PNG shows inline through arelis-chart://."""
    import tempfile

    p = _panel()
    img = QImage(40, 20, QImage.Format.Format_RGB32)
    img.fill(0xFF3366AA)
    path = os.path.join(tempfile.mkdtemp(), "chart.png")
    img.save(path)
    p.add_chart_image("chart.png", path)
    names = [f.name() for f in _all_images(p.view.document())]
    assert any(n.startswith("arelis-chart:") for n in names)
    assert p.view.loadResource(2, QUrl("arelis-chart://c/not-registered")) is None


def _all_images(doc):
    out, cur = [], QTextCursor(doc)
    for pos in range(doc.characterCount() - 1):
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if cur.selectedText() == "\ufffc" and cur.charFormat().isImageFormat():
            out.append(cur.charFormat().toImageFormat())
    return out


# ---------------------------------------------------------------- GUARDS (pass on main, must keep passing)


def test_guard_prices_stay_text():
    p = _panel()
    _reply(p, "It costs $5 and $10.")
    assert _math_images(p.view.document()) == []
    assert "$5" in p.view.toPlainText()


def test_guard_model_markup_never_becomes_an_image():
    p = _panel()
    _reply(p, '<img src="file:///etc/hosts"> ![x](https://example.com/a.png) [[ARELIS_IMATH_0]]')
    assert _all_images(p.view.document()) == []


def test_guard_inline_code_tex_stays_literal():
    p = _panel()
    _reply(p, "Type `$\\frac{a}{b}$` in your editor.")
    assert _math_images(p.view.document()) == []
    assert "\\frac{a}{b}" in p.view.toPlainText()


def test_guard_copy_act_still_copies_raw_markdown():
    p = _panel()
    _reply(p, f"Area is ${FRAC}$.")
    p._copy_last()
    assert QApplication.clipboard().text() == f"Area is ${FRAC}$."
