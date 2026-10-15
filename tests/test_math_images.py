"""Math images in chat.

ziamath draws the picture. Unicode stays the fallback. matplotlib mathtext
is not in this chain.

On main 377d9b4, five of these tests failed: a matrix stayed unicode, there
was no engine hook to patch, ``e^{i\\pi}`` stayed text, ``prepare_tex`` did
not exist, and the installer did not name QtSvg or ziamath. The other
behaviour tests already passed. The four guards passed and still must.
Offscreen, same app as the rest of the suite.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextCursor, QTextDocument


@pytest.fixture(autouse=True)
def _qt(qt_app):
    """A finished warm-up, an empty picture cache, and a fresh reply budget.

    Those three are process globals. A previous test can leave a cached
    miss or a budget already spent, and the next reply then draws unicode.
    """
    from arelis.ui.math_images import begin_reply, clear_cache, wait_prewarm

    assert wait_prewarm(), "math warm-up did not finish"
    clear_cache()
    begin_reply()
    yield qt_app
    clear_cache()
    begin_reply()

FRAC = r"\frac{a}{b}"
SUM = r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}"
PMATRIX = r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}"
NESTED = r"\frac{" * 30 + "x" + "}" * 30


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


def test_a_reply_during_warm_up_still_draws():
    """Warm-up holds the engine. The reply waits for that, then draws.
    After warm-up a busy lock does not wait: this thread would deadlock
    on itself."""
    import threading
    import time

    import arelis.ui.math_images as mi

    mi.clear_cache()
    mi.begin_reply()
    assert mi._LOCK.acquire(timeout=2)
    mi._WARM_DONE.clear()

    def release() -> None:
        time.sleep(0.05)
        mi._LOCK.release()
        mi._WARM_DONE.set()

    helper = threading.Thread(target=release, daemon=True)
    helper.start()
    try:
        image = mi.render_qimage(
            FRAC, True, color="#f8f1ea", px=14, dpr=2.0, max_width=400, give_up=True
        )
        assert image is not None and not image.isNull()
    finally:
        helper.join(2)
        mi._WARM_DONE.set()
        if mi._LOCK.locked():
            mi._LOCK.release()

    assert mi._LOCK.acquire(blocking=False)
    try:
        started = time.perf_counter()
        missed = mi.render_qimage(
            r"\sqrt{2}", True, color="#f8f1ea", px=14, dpr=2.0, max_width=400, give_up=True
        )
        waited = time.perf_counter() - started
    finally:
        mi._LOCK.release()
    assert missed is None
    assert waited < 0.2


def test_simple_inline_math_stays_text_and_structured_inline_becomes_an_image():
    from arelis.ui.math_images import wants_image

    for tex in (r"x^2", r"A \cup B", r"x_n", r"p \implies q", r"30^\circ"):
        assert not wants_image(tex, display=False), tex
    # Greek is an image. The desk face has no Greek, so the unicode line vanishes.
    for tex in (
        FRAC,
        r"\sqrt{2}",
        r"\sum_{i=1}^n i",
        r"e^{i\pi}",
        r"\binom{n}{k}",
        PMATRIX,
        r"\overline{z}",
        r"\alpha + \beta",
        r"\theta",
        r"\Delta > 0",
    ):
        assert wants_image(tex, display=False), tex
    assert wants_image(r"x^2", display=True)
    assert wants_image("x" * 1001, display=True) is False


def test_align_and_equation_lose_their_numbers():
    from arelis.ui.math_images import prepare_tex

    assert "aligned" in prepare_tex(r"\begin{align} a &= b \\ c &= d \end{align}")
    assert "\\tag" not in prepare_tex(r"E = mc^2 \tag{1}")
    assert "\\color" not in prepare_tex(r"\color{red} x")


def _ink_span(mask: np.ndarray) -> tuple[int, int]:
    ink = mask > 64
    cols = np.flatnonzero(ink.any(axis=0))
    rows = np.flatnonzero(ink.any(axis=1))
    if cols.size == 0 or rows.size == 0:
        return (0, 0)
    return (int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


def _max_row_coverage(mask: np.ndarray) -> float:
    """Share of the ink width covered by the fullest row.

    A rule crosses the gap between columns. A row of glyphs does not.
    """
    ink = mask > 64
    cols = np.flatnonzero(ink.any(axis=0))
    if cols.size == 0:
        return 0.0
    body = ink[:, int(cols[0]) : int(cols[-1]) + 1]
    return float(body.mean(axis=1).max())


def test_installer_ships_qtsvg_ziamath_and_the_stix_licence():
    import importlib.util
    from pathlib import Path

    root = Path(__import__("arelis").__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("_b", root / "win-installer" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "QtSvg" in module.QT_MODULES and "ziamath" in module.REQUIRED_IMPORTS
    lock = (root / "win-installer" / "requirements-win-amd64-cp314.txt").read_text()
    mac = (root / "mac-installer" / "requirements-macos-arm64-cp313.txt").read_text()
    for pkg in ("ziamath==", "ziafont==", "latex2mathml=="):
        assert pkg in lock
        assert pkg in mac
    assert (root / "arelis" / "ui" / "fonts" / "OFL-STIXTwoMath.txt").is_file()


def _baseline_gap(image: QImage, font) -> float:
    """Text x bottom minus formula x bottom, in logical pixels.

    Same measurement as the ziamath baseline sweep: paint ``xx`` beside the
    padded image at 2x and compare the lowest ink in each run.
    """
    from PySide6.QtGui import QColor, QPainter, QTextDocument

    document = QTextDocument()
    document.setDefaultFont(font)
    document.addResource(
        QTextDocument.ResourceType.ImageResource,
        QUrl("arelis-math://b"),
        image,
    )
    document.setHtml(
        '<p style="color:#ffffff; margin:0;">'
        'xx<img src="arelis-math://b" style="vertical-align:middle"/>'
        "</p>"
    )
    document.setTextWidth(400)
    scale = 2
    canvas = QImage(400 * scale, 160 * scale, QImage.Format.Format_RGBA8888)
    canvas.setDevicePixelRatio(scale)
    canvas.fill(QColor("#000000"))
    painter = QPainter(canvas)
    document.drawContents(painter)
    painter.end()
    plane = _luma(canvas)
    ink = plane.max(axis=0) > 128
    cols = np.flatnonzero(ink)
    assert cols.size > 0
    start = int(cols[0])

    def run_end(col: int, want: bool) -> int:
        while col < ink.shape[0] and bool(ink[col]) is want:
            col += 1
        return col

    text_end = run_end(start, True)
    gap_end = run_end(text_end, False)
    formula_end = run_end(gap_end, True)

    def bottom(c0: int, c1: int) -> int:
        rows = np.flatnonzero(plane[:, c0:c1].max(axis=1) > 128)
        assert rows.size > 0
        return int(rows.max())

    text_bottom = bottom(start, min(start + 4 * scale, text_end))
    formula_bottom = bottom(gap_end, min(gap_end + 4 * scale, formula_end))
    return (formula_bottom - text_bottom) / scale


def _luma(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    height = converted.height()
    width = converted.width()
    stride = converted.bytesPerLine()
    raw = np.frombuffer(converted.constBits(), dtype=np.uint8, count=stride * height)
    rows = raw.reshape(height, stride)
    pixels = rows[:, : width * 4].reshape(height, width, 4)
    return pixels[..., :3].max(axis=2)


def _all_images(doc):
    out, cur = [], QTextCursor(doc)
    for pos in range(doc.characterCount() - 1):
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
        if cur.selectedText() == "\ufffc" and cur.charFormat().isImageFormat():
            out.append(cur.charFormat().toImageFormat())
    return out


# ---------------------------------------------------------------- GUARDS (pass on main, must keep passing)


