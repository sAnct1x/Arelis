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
from PySide6.QtGui import QImage, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QApplication


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


def test_a_matrix_renders_as_one_image():
    """pmatrix, cases and aligned are images with ziamath."""
    p = _panel()
    _reply(p, f"$${PMATRIX}$$")
    assert len(_math_images(p.view.document())) == 1
    assert "(1 2; 3 4)" not in p.view.toPlainText()


def test_cases_aligned_array_and_underbrace_render():
    body = "\n\n".join(
        f"$${tex}$$"
        for tex in (
            r"f(x) = \begin{cases} x & x \geq 0 \\ -x & x < 0 \end{cases}",
            r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
            r"\begin{array}{cc} 1 & 0 \\ 0 & 1 \end{array}",
            r"\underbrace{a+b}_{n}",
        )
    )
    p = _panel()
    _reply(p, body)
    assert len(_math_images(p.view.document())) == 4


def test_a_slow_first_formula_does_not_drop_the_rest_of_a_short_reply(monkeypatch):
    """The reply budget used to stop after one slow draw. The other three
    stayed unicode. A short answer still draws them."""
    import time

    import arelis.ui.math_images as mi

    real = mi._svg_for
    calls = {"n": 0}

    def slow(tex, px, display):
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(0.25)
        return real(tex, px, display)

    monkeypatch.setattr(mi, "_svg_for", slow)
    body = "\n\n".join(
        f"$${tex}$$"
        for tex in (
            r"f(x) = \begin{cases} x & x \geq 0 \\ -x & x < 0 \end{cases}",
            r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
            r"\begin{array}{cc} 1 & 0 \\ 0 & 1 \end{array}",
            r"\underbrace{a+b}_{n}",
        )
    )
    p = _panel()
    _reply(p, body)
    assert len(_math_images(p.view.document())) == 4
    assert calls["n"] == 4


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


def test_a_long_reply_still_stops_when_the_time_cap_is_spent():
    """The floor does not cancel the cap. Past the floor, a spent budget stays unicode."""
    import arelis.ui.math_images as mi

    mi.begin_reply()
    mi._BUDGET.count = mi._DRAW_FLOOR
    mi._BUDGET.spent = mi._TIME_CAP_S
    assert mi.math_html(0, FRAC, "a/b", True) is None


def test_a_formula_that_cannot_render_falls_back_to_readable_unicode():
    """The fraction is an image. A 30-deep fraction raises inside ziamath and
    stays unicode, never raw TeX or a broken-image box."""
    p = _panel()
    _reply(p, f"First ${FRAC}$ then $${NESTED}$$")
    assert len(_math_images(p.view.document())) == 1
    text = p.view.toPlainText()
    assert "\\frac" not in text and "x" in text


def test_engine_exception_falls_back_to_unicode(monkeypatch):
    """Any exception from the engine, including AssertionError, stays unicode."""
    import arelis.ui.math_images as mi

    def _boom(*_args, **_kwargs):
        raise AssertionError("boom")

    monkeypatch.setattr(mi, "_svg_for", _boom)
    p = _panel()
    _reply(p, f"$${FRAC}$$")
    assert _math_images(p.view.document()) == []
    assert "a/b" in p.view.toPlainText()


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


def test_overline_rule_takes_the_theme_colour():
    """The overline rule is hard-coded black in ziamath 0.13. Tint it."""
    from arelis.ui.theme import COLORS

    p = _panel()
    _reply(p, r"$$\overline{z}$$")
    img = _resource(p.view, _math_images(p.view.document())[0]).convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    raw = np.frombuffer(img.constBits(), np.uint8)
    stride = img.bytesPerLine()
    rows = raw.reshape(img.height(), stride)
    pixels = rows[:, : img.width() * 4].reshape(img.height(), img.width(), 4)
    top = pixels[: max(1, pixels.shape[0] // 3)]
    solid = top[top[..., 3] > 200][:, :3]
    want = np.array([int(COLORS["text"][i : i + 2], 16) for i in (1, 3, 5)])
    assert len(solid) > 0 and np.abs(np.median(solid, axis=0) - want).max() <= 8


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


def test_row_spacing_argument_is_not_literal_text():
    """FAILFIRST on b757d3c. ``\\\\[6pt]`` stayed in prepare_tex, and the
    aligned picture was wider than the same rows without the bracket.
    A trailing ``\\\\[6pt]`` added a text row, so the picture was taller."""
    from arelis.ui.math_images import prepare_tex, render_mask

    spaced = r"\begin{aligned} a &= b \\[6pt] c &= d \end{aligned}"
    plain = r"\begin{aligned} a &= b \\ c &= d \end{aligned}"
    problems = []
    prepared = prepare_tex(spaced)
    if "[6pt]" in prepared:
        problems.append(prepared)
    em = prepare_tex(r"\begin{array}{cc} a & b \\[0.5em] c & d \end{array}")
    if "[0.5em]" in em or "0.5em" in em:
        problems.append(em)
    neg = prepare_tex(r"a \\[-2pt] b")
    if "-2pt" in neg:
        problems.append(neg)
    dotted = prepare_tex(r"a \\[.5em] b")
    if ".5em" in dotted:
        problems.append(dotted)
    starred = prepare_tex(r"a \\*[6pt] b")
    if "6pt" in starred:
        problems.append(starred)
    gapped = prepare_tex(r"a \\ [12pt] b")
    if "12pt" in gapped:
        problems.append(gapped)
    if "[note]" not in prepare_tex(r"a \\[note] b"):
        problems.append("ate a bracket that is not a length")
    if prepare_tex(r"\sqrt[3]{x}") != r"\sqrt[3]{x}":
        problems.append(prepare_tex(r"\sqrt[3]{x}"))

    wide = render_mask(spaced, True, 16, 2.0)
    slim = render_mask(plain, True, 16, 2.0)
    if wide is None or slim is None:
        problems.append("aligned spacing did not render")
    elif _ink_span(wide)[0] > _ink_span(slim)[0] * 1.15:
        problems.append(f"aligned width {_ink_span(wide)[0]} vs {_ink_span(slim)[0]}")

    em_wide = render_mask(r"\begin{array}{cc} a & b \\[0.5em] c & d \end{array}", True, 16, 2.0)
    em_slim = render_mask(r"\begin{array}{cc} a & b \\ c & d \end{array}", True, 16, 2.0)
    if em_wide is None or em_slim is None:
        problems.append("em spacing did not render")
    elif _ink_span(em_wide)[0] > _ink_span(em_slim)[0] * 1.15:
        problems.append(f"em width {_ink_span(em_wide)[0]} vs {_ink_span(em_slim)[0]}")

    trail = render_mask(
        r"\begin{aligned} a &= b \\ c &= d \\[6pt] \end{aligned}",
        True,
        16,
        2.0,
    )
    if trail is None or slim is None:
        problems.append("trailing spacing did not render")
    elif _ink_span(trail)[1] > _ink_span(slim)[1] * 1.35:
        problems.append(f"trailing height {_ink_span(trail)[1]} vs {_ink_span(slim)[1]}")
    assert not problems, problems


def test_hline_draws_a_rule_instead_of_disappearing():
    """FAILFIRST on b757d3c. ``\\hline`` in array and aligned matched the
    picture with the command deleted. tabular did not render. gathered
    drew the command name."""
    from arelis.ui.math_images import prepare_tex, render_mask

    problems = []
    kept = prepare_tex(r"\begin{array}{cc} a & b \\ \hline c & d \end{array}")
    if r"\hline" not in kept:
        problems.append(f"array dropped hline: {kept}")
    outside = prepare_tex(r"\begin{gathered} a \\ \hline b \end{gathered}")
    if "hline" in outside:
        problems.append(f"gathered kept the command: {outside}")
    tabular = prepare_tex(r"\begin{tabular}{cc} a & b \\ \hline c & d \end{tabular}")
    if "tabular" in tabular or r"\hline" not in tabular:
        problems.append(f"tabular: {tabular}")

    pairs = (
        (
            r"\begin{array}{cc} a & b \\ \hline c & d \end{array}",
            r"\begin{array}{cc} a & b \\ c & d \end{array}",
        ),
        (
            r"\begin{aligned} a &= b \\ c &= d \\ \hline \end{aligned}",
            r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
        ),
        (
            r"\begin{aligned} x + y &= 5 \\ x - y &= 1 \\[6pt] \hline \end{aligned}",
            r"\begin{aligned} x + y &= 5 \\ x - y &= 1 \end{aligned}",
        ),
    )
    for raw, bare_tex in pairs:
        ruled = render_mask(raw, True, 16, 2.0)
        bare = render_mask(bare_tex, True, 16, 2.0)
        if ruled is None or bare is None:
            problems.append(f"missing picture for {raw}")
            continue
        coverage = _max_row_coverage(ruled)
        if coverage < 0.85:
            problems.append(f"no rule in {raw} ({coverage:.2f})")
        if _max_row_coverage(bare) >= 0.85:
            problems.append(f"bare table looks ruled: {bare_tex}")
        if "[6pt]" in prepare_tex(raw):
            problems.append(f"spacing still in {prepare_tex(raw)}")
        raw_h = _ink_span(ruled)[1]
        bare_h = _ink_span(bare)[1]
        if bare_h and raw_h > bare_h * 1.45:
            problems.append(f"still a text row in {raw}: {raw_h} vs {bare_h}")

    tab = render_mask(r"\begin{tabular}{cc} a & b \\ \hline c & d \end{tabular}", True, 16, 2.0)
    if tab is None or _max_row_coverage(tab) < 0.85:
        got = None if tab is None else f"{_max_row_coverage(tab):.2f}"
        problems.append(f"tabular rule {got}")

    gathered = render_mask(r"\begin{gathered} a \\ \hline b \end{gathered}", True, 16, 2.0)
    gathered_plain = render_mask(r"\begin{gathered} a \\ b \end{gathered}", True, 16, 2.0)
    if gathered is None or gathered_plain is None:
        problems.append("gathered did not render")
    elif _ink_span(gathered)[0] > _ink_span(gathered_plain)[0] * 1.3:
        problems.append(
            f"gathered width {_ink_span(gathered)[0]} vs {_ink_span(gathered_plain)[0]}"
        )
    assert not problems, problems


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
    """Within 1 px of the text baseline (vertical-align:middle plus padding)."""
    from PySide6.QtGui import QFont

    p = _panel()
    _reply(p, r"xx $x_n^2$")
    fmt = _math_images(p.view.document())[0]
    assert fmt.verticalAlignment().name == "AlignMiddle"
    image = _resource(p.view, fmt)
    font = QFont(p.view.font())
    font.setPixelSize(p.view._math_px)
    gap = _baseline_gap(image, font)
    assert abs(gap) <= 1.0, gap


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
