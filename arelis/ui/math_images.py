"""Draw chat math with ziamath.

The picture is an SVG from ziamath (STIX Two Math), rastered by Qt, then
tinted with the theme text colour. Unicode from mathtext.py is the fallback
when a formula is simple, too long, too wide, or the engine fails.

matplotlib mathtext is not in this chain. Matrices, cases, aligned, array,
and underbrace are drawn here. Row spacing written ``\\\\[6pt]`` or
``\\\\[0.5em]`` is removed, because ziamath draws that bracket as text.
``\\hline`` is drawn on a table. ``tabular`` is drawn as ``array``, which
is the form ziamath accepts.

The HTML address is ``arelis-math://f/<sha1>`` with no colour and no size
in it, so a theme change recolours the cached mask and a text-scale change
parses again.
"""

from __future__ import annotations

import atexit
import hashlib
import html
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from arelis.mathtext import tex_to_plain

log = logging.getLogger(__name__)

MATH_SCHEME = "arelis-math"

# One reply may spend this long, or this many formulas, on images. The rest
# stay unicode so a huge answer cannot stall the bubble. The first few are
# drawn even when they are slow. One cold formula used to spend the whole
# cap, and the rest of a short answer came out as unicode. A fast machine
# finishes those inside the cap, so a long answer still stops where it used to.
_FORMULA_CAP = 60
_TIME_CAP_S = 0.200
_DRAW_FLOOR = 8

# A reply that arrives while warm-up still holds the engine waits at most
# this long. Giving up at once left the formula as unicode.
_LOCK_WAIT_S = 2.0

# Anything longer than this stays unicode. A few hundred sums already cost
# more than a frame, and a 30-deep fraction raises inside ziamath.
_MAX_TEX = 1000

# vertical-align:middle puts the image centre on the text. The formula
# baseline needs to sit 0.35 x-height above that centre.
_BASELINE_K = 0.35

# Shrink a formula that is wider than the bubble down to 75 percent of the
# bubble by raising the device pixel ratio. Past 3x the raster is mush and
# the unicode line can wrap, so give up.
_SHRINK_LIMIT = 3.0

# Inline structure unicode cannot draw. Simple ``x^2`` and Greek are absent
# on purpose. ``(?![A-Za-z])`` keeps ``\int`` from eating ``\iint``.
_STRUCTURE = re.compile(
    r"\\(?:[dtc]?frac|[dt]?binom|sqrt|over|choose|sum|prod|coprod|"
    r"int|iint|iiint|oint|lim|limsup|liminf|bigcup|bigcap|"
    r"bigoplus|bigotimes|begin|overline|underline|overbrace|underbrace|"
    r"widehat|widetilde|overset|underset|stackrel|xrightarrow|xleftarrow|"
    r"boxed|substack|left)(?![A-Za-z])"
)
# One chat glyph cannot carry both a subscript and a superscript, so
# ``x_n^2`` is a picture even though the unicode line has neither mark.
_STACKED = re.compile(r"[_^](?:\{[^{}]*\}|[A-Za-z0-9\\]+)\s*[_^]")

_DROP = re.compile(
    r"\\(?:tag|label|color)\s*\{[^{}]*\}|\\(?:nonumber|notag)(?![A-Za-z])"
)
_EQUATION = re.compile(
    r"\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}",
    re.DOTALL,
)
# align numbers its rows. gathered and aligned do not. Longer names go
# first so ``align*`` is not left as ``aligned*``.
_ENVS: tuple[tuple[str, str], ...] = (
    ("align*", "aligned"),
    ("flalign*", "aligned"),
    ("eqnarray*", "aligned"),
    ("flalign", "aligned"),
    ("eqnarray", "aligned"),
    ("align", "aligned"),
    ("split", "aligned"),
    ("gather*", "gathered"),
    ("multline*", "gathered"),
    ("gather", "gathered"),
    ("multline", "gathered"),
)

# ``\\[6pt]`` and ``\\[0.5em]``. The break stays. The length is not a
# glyph. A star form ``\\*[6pt]`` is the same break in a chat bubble.
_ROW_SKIP = re.compile(
    r"\\\\(?:\*)?\s*\[\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)\s*"
    r"(?:pt|em|ex|mu|px|bp|pc|dd|cc|cm|mm|in|sp)\s*\]",
    re.IGNORECASE,
)
_HLINE = re.compile(r"\\(?:hline|hdashline)(?![A-Za-z])")
_BEGIN_ENV = re.compile(r"\\begin\{([A-Za-z*]+)\}")
_END_ENV = re.compile(r"\\end\{([A-Za-z*]+)\}")
# Environments latex2mathml turns into an mtable, after the renames above.
# ``gathered`` is not one of them. A rule there would be the word hline.
_RULE_ENVS = frozenset(
    {
        "array",
        "matrix",
        "pmatrix",
        "bmatrix",
        "Bmatrix",
        "vmatrix",
        "Vmatrix",
        "smallmatrix",
        "cases",
        "aligned",
        "align",
        "align*",
        "split",
        "eqnarray",
        "eqnarray*",
        "flalign",
        "flalign*",
        "substack",
        "matrix*",
        "pmatrix*",
        "bmatrix*",
        "Bmatrix*",
        "vmatrix*",
        "Vmatrix*",
        "eqalign",
        "eqalignno",
        "displaylines",
    }
)

_FAIL = object()
_LOCK = threading.Lock()
_PREWARMED = False
_WARM_DONE = threading.Event()
_WARM_DONE.set()


class _BusyError(Exception):
    """The engine is busy and the short wait is over. This formula stays unicode."""


@dataclass(frozen=True)
class MathSpan:
    index: int
    tex: str
    plain: str
    display: bool


@dataclass
class RenderTarget:
    color: str = "#f8f1ea"
    px: int = 14
    dpr: float = 2.0
    max_width: float = 0.0
    family: str = ""


class _Budget:
    def __init__(self) -> None:
        self.count = 0
        self.spent = 0.0

    def begin(self) -> None:
        self.count = 0
        self.spent = 0.0

    def allow(self) -> bool:
        if self.count >= _FORMULA_CAP:
            return False
        if self.count < _DRAW_FLOOR:
            return True
        return self.spent < _TIME_CAP_S

    def add(self, seconds: float) -> None:
        self.count += 1
        self.spent += max(0.0, seconds)


class MathCache:
    """LRU of alpha masks and of recoloured images.

    The mask key is the formula, the size, and the raster scale. Colour is
    not in it, so a theme switch does not parse again.
    """

    def __init__(self, limit: int = 1024) -> None:
        self.limit = limit
        self._masks: OrderedDict[str, np.ndarray | object] = OrderedDict()
        self._images: OrderedDict[str, QImage] = OrderedDict()

    def mask(self, key: str) -> np.ndarray | object | None:
        if key not in self._masks:
            return None
        self._masks.move_to_end(key)
        return self._masks[key]

    def put_mask(self, key: str, value: np.ndarray | object) -> None:
        self._masks[key] = value
        self._masks.move_to_end(key)
        while len(self._masks) > self.limit:
            self._masks.popitem(last=False)

    def image(self, key: str) -> QImage | None:
        found = self._images.get(key)
        if found is None:
            return None
        self._images.move_to_end(key)
        return found

    def put_image(self, key: str, image: QImage) -> None:
        self._images[key] = image
        self._images.move_to_end(key)
        while len(self._images) > self.limit:
            self._images.popitem(last=False)

    def clear(self) -> None:
        self._masks.clear()
        self._images.clear()


_CACHE = MathCache()
_SPANS: dict[str, MathSpan] = {}
_TARGET = RenderTarget()
_BUDGET = _Budget()


def set_target(
    *,
    color: str,
    px: int,
    dpr: float,
    max_width: float,
    family: str = "",
) -> None:
    """Size and ink for the reply about to be rendered."""
    _TARGET.color = color or _TARGET.color
    _TARGET.px = max(1, int(px))
    _TARGET.dpr = float(dpr) if dpr and dpr > 0 else 2.0
    _TARGET.max_width = max(0.0, float(max_width))
    _TARGET.family = family or ""


def begin_reply() -> None:
    """Start the per-reply time and formula budget."""
    _BUDGET.begin()


def clear_cache() -> None:
    """Drop cached masks. Tests call this so a patched engine is used."""
    _CACHE.clear()


def prepare_tex(tex: str) -> str:
    """Strip numbering and colour, and rename environments ziamath numbers.

    ``align`` becomes ``aligned``, ``gather`` and ``multline`` become
    ``gathered``, and ``equation`` is unwrapped. ``\\tag``, ``\\label``,
    ``\\nonumber``, ``\\notag``, and ``\\color`` are removed. The theme
    owns the ink, and a chat bubble is not a numbered paper.

    ``\\\\[6pt]`` loses the length and keeps the row break. ``tabular``
    becomes ``array``. ``\\hline`` stays inside a table so the picture
    can draw it, and is removed anywhere else so the command name is
    not drawn.
    """
    text = _DROP.sub("", tex or "")
    text = _EQUATION.sub(r"\1", text)
    for name, dest in _ENVS:
        text = _rename_env(text, name, dest)
    text = _rewrite_tabular(text)
    text = _ROW_SKIP.sub(_keep_row_break, text)
    text = _drop_loose_hlines(text)
    return text.strip()


def wants_image(tex: str, display: bool) -> bool:
    """True when this span should try an image instead of unicode."""
    src = (tex or "").strip()
    if not src or len(src) > _MAX_TEX:
        return False
    if display:
        return True
    if _STRUCTURE.search(src):
        return True
    plain = tex_to_plain(src)
    if "^" in plain or "_" in plain:
        return True
    return _STACKED.search(src) is not None


def formula_id(tex: str, display: bool) -> str:
    return hashlib.sha1(f"{tex}|{int(bool(display))}".encode()).hexdigest()


def formula_url(tex: str, display: bool) -> str:
    return f"{MATH_SCHEME}://f/{formula_id(tex, display)}"


def span_for_url(url: str) -> MathSpan | None:
    token = (url or "").rstrip("/").split("/")[-1]
    return _SPANS.get(token)


def is_display_formula(url: str) -> bool:
    span = span_for_url(url)
    return bool(span and span.display)


def latex_for_copy(url: str, alt: str, tip: str) -> str:
    """``$tex$`` or ``$$tex$$`` for one math image in a selection."""
    span = span_for_url(url)
    tex = (span.tex if span is not None else "") or alt or tip
    if span is not None and span.display:
        return f"$${tex}$$"
    return f"${tex}$"


def prewarm() -> None:
    """Import ziamath and draw one formula off the GUI thread.

    The first import is about a tenth of a second. A reply that arrives
    while this still holds the lock waits for it, up to ``_LOCK_WAIT_S``,
    and then draws.
    """
    global _PREWARMED
    if _PREWARMED:
        return
    _PREWARMED = True
    _WARM_DONE.clear()

    def run() -> None:
        try:
            if not _LOCK.acquire(timeout=30):
                return
            try:
                _svg_for(r"x^2+\frac{a}{b}", 14, False)
            finally:
                _LOCK.release()
        except Exception:
            # A failed warm-up only delays the first formula. The window
            # still answers, so this stays a quiet log.
            log.debug("math warm-up failed", exc_info=True)
        finally:
            _WARM_DONE.set()

    threading.Thread(target=run, name="arelis-math-prewarm", daemon=True).start()
    atexit.register(lambda: _WARM_DONE.wait(5))


def wait_prewarm(timeout: float = 30.0) -> bool:
    """Block until the background import has finished.

    The window does not call this. A test paints a reply in the same
    breath it builds the panel, so the harness waits here instead of
    making the GUI thread wait on the lock.
    """
    prewarm()
    return _WARM_DONE.wait(timeout)


def math_html(index: int, tex: str, plain: str, display: bool) -> str | None:
    """An ``<img>`` for one span, or None when the unicode line should stay."""
    span = MathSpan(
        index=index,
        tex=(tex or "").strip(),
        plain=plain or "",
        display=bool(display),
    )
    if not span.tex or not wants_image(span.tex, span.display):
        return None
    if not _BUDGET.allow():
        return None
    started = time.perf_counter()
    try:
        image = render_qimage(
            span.tex,
            span.display,
            color=_TARGET.color,
            px=_TARGET.px,
            dpr=_TARGET.dpr,
            max_width=_TARGET.max_width,
            give_up=True,
        )
    finally:
        _BUDGET.add(time.perf_counter() - started)
    if image is None:
        return None
    fid = formula_id(span.tex, span.display)
    _SPANS[fid] = span
    alt = html.escape(span.tex, quote=True)
    url = formula_url(span.tex, span.display)
    return (
        f'<img src="{url}" alt="{alt}" title="{alt}" style="vertical-align:middle"/>'
    )


def image_for_url(url: str) -> QImage | None:
    """The image for a formula we already decided to draw.

    Unknown hashes are refused. A later theme or size change may recolour
    or re-parse, but it does not fall back to unicode: the HTML already
    contains the image.
    """
    span = span_for_url(url)
    if span is None:
        return None
    return render_qimage(
        span.tex,
        span.display,
        color=_TARGET.color,
        px=_TARGET.px,
        dpr=_TARGET.dpr,
        max_width=_TARGET.max_width,
        give_up=False,
    )


def render_mask(tex: str, display: bool, px: int, dpr: float) -> np.ndarray | None:
    """Padded alpha mask, or None when ziamath cannot draw the formula."""
    key = _mask_key(tex, display, px, dpr)
    cached = _CACHE.mask(key)
    if cached is _FAIL:
        return None
    if isinstance(cached, np.ndarray):
        return cached
    try:
        built = _build_mask(tex, display, px, dpr)
    except _BusyError:
        return None
    if built is None:
        _CACHE.put_mask(key, _FAIL)
        return None
    _CACHE.put_mask(key, built)
    return built


def colorize(mask: np.ndarray, hex_color: str) -> np.ndarray:
    """Apply one flat ink colour to an alpha mask. Theme switches use this."""
    alpha = mask if mask.ndim == 2 else _as_alpha(mask)
    height, width = alpha.shape
    red, green, blue = _rgb(hex_color)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = red
    rgba[..., 1] = green
    rgba[..., 2] = blue
    rgba[..., 3] = alpha
    return rgba


def render_qimage(
    tex: str,
    display: bool,
    *,
    color: str,
    px: int,
    dpr: float,
    max_width: float,
    give_up: bool,
) -> QImage | None:
    mask = render_mask(tex, display, px, dpr)
    if mask is None:
        return None
    key = _image_key(_mask_key(tex, display, px, dpr), color)
    cached = _CACHE.image(key)
    if cached is None:
        cached = _qimage(colorize(mask, color), dpr)
        _CACHE.put_image(key, cached)
    return _fit_width(cached.copy(), max_width, give_up=give_up)


def _svg_for(tex: str, px: int, display: bool) -> str:
    """Black SVG. ``svg2`` stays off or Qt drops the glyphs.

    ziamath reads ``rowlines`` and does not draw it. The rule is added
    here. A rule under the last row hangs out of the box, so the box
    grows downward until the viewBox contains the stroke.
    """
    import ziamath
    from ziafont.fonttypes import BBox

    ziamath.config.svg2 = False
    size = float(px) * (1.15 if display else 1.0)
    drawn = ziamath.Latex(tex, size=size, color="black", inline=not display)
    stick = _paint_row_rules(drawn.node)
    extra = stick - float(drawn.margin) + 0.4
    if extra > 0:
        box = drawn.node.bbox
        drawn.node.bbox = BBox(box.xmin, box.xmax, box.ymin - extra, box.ymax)
    return drawn.svg()


def _acquire_engine() -> bool:
    """Take the engine. During warm-up, wait until that thread lets go.

    Warm-up releases the lock before it marks itself done, so waiting on
    the event cannot deadlock. Once warm-up has finished, a busy lock is
    this thread already inside a render. Waiting there would deadlock, so
    that miss stays unicode.
    """
    if _LOCK.acquire(blocking=False):
        return True
    if not _WARM_DONE.is_set():
        _WARM_DONE.wait(_LOCK_WAIT_S)
    return _LOCK.acquire(blocking=False)


def _build_mask(tex: str, display: bool, px: int, dpr: float) -> np.ndarray | None:
    if not _acquire_engine():
        raise _BusyError()
    try:
        prepared = prepare_tex(tex)
        if not prepared:
            return None
        try:
            svg = _svg_for(prepared, px, display)
            return _mask_from_svg(svg, dpr, _x_height(px, _TARGET.family))
        except Exception:
            # ziamath raises several types, including AssertionError on a
            # very deep fraction. That miss is the unicode line.
            log.debug("ziamath could not draw a formula", exc_info=True)
            return None
    finally:
        _LOCK.release()


def _mask_from_svg(svg: str, dpr: float, xheight: float) -> np.ndarray:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("svg did not parse")
    box = renderer.viewBoxF()
    width = float(box.width())
    height = float(box.height())
    if width <= 0 or height <= 0:
        raise ValueError("empty formula")
    # The baseline is y=0 in the viewBox. y is negative above it.
    depth = height + float(box.y())
    above = height - depth
    k = _BASELINE_K * xheight
    pad = (above - k) - (depth + k)
    logical_h = height + abs(pad)
    top = abs(pad) if pad < 0 else 0.0
    pix_w = max(1, round(width * dpr))
    pix_h = max(1, round(logical_h * dpr))
    image = QImage(pix_w, pix_h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter, QRectF(0, top * dpr, width * dpr, height * dpr))
    finally:
        painter.end()
    alpha = _alpha_plane(image)
    if alpha.size == 0 or int(alpha.max()) == 0:
        raise ValueError("blank formula")
    return alpha


def _keep_row_break(_match: re.Match[str]) -> str:
    return "\\\\"


def _rewrite_tabular(text: str) -> str:
    """ziamath rejects ``tabular``. The column spec is the same as array."""
    text = re.sub(
        r"\\begin\{tabular\*\}\s*\{[^{}]*\}",
        r"\\begin{array}",
        text,
    )
    text = re.sub(r"\\begin\{tabular\}", r"\\begin{array}", text)
    return re.sub(r"\\end\{tabular\*?\}", r"\\end{array}", text)


def _drop_loose_hlines(text: str) -> str:
    """Remove ``\\hline`` that would be drawn as the word hline.

    Inside an environment that becomes a table, the command stays. The
    renderer turns that into a rule.
    """
    depth = 0
    out: list[str] = []
    index = 0
    while index < len(text):
        began = _BEGIN_ENV.match(text, index)
        if began:
            if began.group(1) in _RULE_ENVS:
                depth += 1
            out.append(began.group(0))
            index = began.end()
            continue
        ended = _END_ENV.match(text, index)
        if ended:
            if ended.group(1) in _RULE_ENVS and depth:
                depth -= 1
            out.append(ended.group(0))
            index = ended.end()
            continue
        rule = _HLINE.match(text, index)
        if rule and depth == 0:
            index = rule.end()
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _paint_row_rules(node: Any) -> float:
    """Draw table rules. Returns how far a rule hangs below a table box."""
    from ziamath.nodes.mnode import Mnode
    from ziamath.nodes.mtable import Mtable

    stick = 0.0
    children = [child for child in getattr(node, "nodes", ()) if isinstance(child, Mnode)]
    for child in children:
        stick = max(stick, _paint_row_rules(child))
    if isinstance(node, Mtable):
        stick = max(stick, _paint_table_rules(node))
    return stick


def _paint_table_rules(table: Any) -> float:
    from ziamath.drawable import HLine

    specs = (table.element.get("rowlines") or "").split()
    if not specs or all(spec == "none" for spec in specs):
        return 0.0
    rows = _rule_rows(table)
    if not rows:
        return 0.0
    lw = float(table.units_to_points(table.font.math.consts.radicalRuleThickness))
    if lw < 0.6:
        lw = 0.6
    width = float(table.bbox.xmax - table.bbox.xmin)
    if width <= 0:
        return 0.0
    x0 = float(table.bbox.xmin)
    gaps = len(rows) - 1
    for index in range(gaps):
        spec = specs[index] if index < len(specs) else specs[-1]
        if spec == "none":
            continue
        mid = (rows[index]["bottom"] + rows[index + 1]["top"]) / 2
        _add_hline(table, HLine, width, lw, x0, mid - lw / 2)
    if len(specs) <= gaps or specs[gaps] == "none":
        return 0.0
    # latex2mathml records one entry per ``\\hline``, then drops the empty
    # row a trailing break leaves behind. That extra entry is the rule
    # under the last row. The rowlines attribute has no slot for it, and
    # ziamath does not paint the attribute anyway.
    y = rows[-1]["bottom"] + max(lw * 0.35, 0.35)
    _add_hline(table, HLine, width, lw, x0, y)
    hang = (y + lw) - (-float(table.bbox.ymin))
    return hang if hang > 0 else 0.0


def _rule_rows(table: Any) -> list[dict[str, float]]:
    grouped: dict[float, list[Any]] = {}
    for (_x, y), node in zip(table.nodexy, table.nodes, strict=True):
        grouped.setdefault(round(float(y), 3), []).append(node)
    rows = []
    for y in sorted(grouped):
        cells = grouped[y]
        rows.append(
            {
                "bottom": y - min(float(cell.bbox.ymin) for cell in cells),
                "top": y - max(float(cell.bbox.ymax) for cell in cells),
            }
        )
    return rows


def _add_hline(table: Any, hline_cls: type, width: float, lw: float, x: float, y: float) -> None:
    table.nodes.append(hline_cls(width, lw, style=table.style))
    table.nodexy.append((x, y))


def _rename_env(text: str, name: str, dest: str) -> str:
    pattern = re.compile(rf"\\(begin|end)\{{{re.escape(name)}\}}")

    def repl(match: re.Match[str]) -> str:
        return f"\\{match.group(1)}{{{dest}}}"

    return pattern.sub(repl, text)


def _alpha_plane(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    height = converted.height()
    width = converted.width()
    stride = converted.bytesPerLine()
    raw = np.frombuffer(converted.constBits(), dtype=np.uint8, count=stride * height)
    rows = raw.reshape(height, stride)
    pixels = rows[:, : width * 4].reshape(height, width, 4)
    return np.ascontiguousarray(pixels[..., 3])


def _as_alpha(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        arr = arr[..., 3] if arr.shape[-1] == 4 else arr[..., 0]
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0)
        arr = np.rint(arr * 255.0).astype(np.uint8)
    return np.ascontiguousarray(arr)


def _x_height(px: int, family: str) -> float:
    font = QFont()
    if family:
        font.setFamily(family)
    font.setPixelSize(max(1, int(px)))
    height = float(QFontMetricsF(font).xHeight())
    if height <= 0.5:
        return max(1, int(px)) * 0.5
    return height


def _qimage(rgba: np.ndarray, dpr: float) -> QImage:
    rgba = np.ascontiguousarray(rgba)
    height, width, _channels = rgba.shape
    view = QImage(rgba.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
    owned = view.copy()
    owned.setDevicePixelRatio(dpr)
    return owned


def _fit_width(image: QImage, max_width: float, *, give_up: bool) -> QImage | None:
    if image.isNull() or image.width() < 1 or image.height() < 1:
        return None
    dpr = image.devicePixelRatio() or 1.0
    if max_width <= 0:
        return image
    logical = image.width() / dpr
    if logical <= max_width:
        return image
    target = max_width * 0.75
    if target < 8:
        return None if give_up else image
    needed = image.width() / target
    if needed > dpr * _SHRINK_LIMIT and give_up:
        return None
    image.setDevicePixelRatio(needed)
    return image


def _mask_key(tex: str, display: bool, px: int, dpr: float) -> str:
    raw = f"ziamath|{tex}|{int(bool(display))}|{int(px)}|{float(dpr):.2f}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _image_key(mask_key: str, color: str) -> str:
    return hashlib.sha1(f"{mask_key}|{color}".encode()).hexdigest()


def _rgb(color: str) -> tuple[int, int, int]:
    text = (color or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) < 6:
        text = "f8f1ea"
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (248, 241, 234)
