"""Draw chat math with matplotlib mathtext.

The chat font is sans, so the math font is DejaVu Sans too. Display formulas
are images. Inline formulas are images only when unicode cannot show the
structure (a fraction, a root, a sum, an integral, a limit, a big operator,
a stacked script). ``x^2`` and Greek letters stay text, so they can still be
selected and found.

A failed draw, a matrix, a cases block, an array, or an underbrace stays the
unicode line mathtext.py already produces. The HTML address is
``arelis-math://f/<sha1>`` with no colour and no size in it, so a theme change
recolours the cached mask and a text-scale change parses again.
"""

from __future__ import annotations

import atexit
import hashlib
import html
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QFont, QFontMetricsF, QImage

log = logging.getLogger(__name__)

MATH_SCHEME = "arelis-math"

# One reply may spend this long, or this many formulas, on images. The rest
# stay unicode so a huge answer cannot stall the bubble.
_FORMULA_CAP = 60
_TIME_CAP_S = 0.150

# vertical-align:middle puts the image centre on the text. Measured at 2x,
# the formula baseline needs to sit about 0.3 x-height above that centre.
_BASELINE_K = -0.3

# Shrink a formula that is wider than the bubble down to 75 percent of the
# bubble by raising the device pixel ratio. Past 3x the raster is mush and
# the unicode line can wrap, so give up.
_SHRINK_LIMIT = 3.0

_ALIAS_SRC: tuple[tuple[str, str], ...] = (
    (r"\\implies\b", r"\\Longrightarrow"),
    (r"\\iff\b", r"\\Leftrightarrow"),
    (r"\\le\b", r"\\leq"),
    (r"\\ge\b", r"\\geq"),
    (r"\\[dt]frac\b", r"\\frac"),
    (r"\\displaystyle\b|\\textstyle\b|\\nonumber\b|\\notag\b", ""),
    (r"\\[bB]ig{1,2}[lr]?\b", ""),
    (r"\\lvert\b|\\rvert\b", "|"),
    (r"\\lVert\b|\\rVert\b", r"\\|"),
    (r"\\bmod\b", r"\\ \\mathrm{mod}\\ "),
    (r"\\pmod\{([^{}]*)\}", r"\\ (\\mathrm{mod}\\ \1)"),
    (r"\\tag\{([^{}]*)\}", r"\\qquad (\1)"),
    (r"\\color\{[^{}]*\}", ""),
    (r"\\boxed\{", "{"),
    (r"\\stackrel\b", r"\\overset"),
)
_ALIASES = tuple((re.compile(src), repl) for src, repl in _ALIAS_SRC)

_ROW_ENV = re.compile(
    r"\\begin\{(aligned|align\*?|gathered|split)\}(.*?)\\end\{\1\}",
    re.DOTALL,
)

# Inline structure unicode cannot draw. Simple ``x^2`` and Greek are absent
# on purpose. Stacked scripts (``x_n^2``) are here because one atom cannot
# carry both a sub and a super in the chat font.
_STRUCTURE = re.compile(
    r"\\(?:frac|tfrac|dfrac|cfrac|binom|dbinom|tbinom|choose|sqrt|"
    r"sum|prod|coprod|int|iint|iiint|oint|"
    r"bigcup|bigcap|bigvee|bigwedge|bigoplus|bigotimes|bigsqcup|"
    r"lim|limsup|liminf|sup|inf|max|min|"
    r"overline|underline|vec|overrightarrow|overleftarrow|"
    r"overset|underset|stackrel|substack)\b"
)
_STACKED = re.compile(r"[_^](?:\{[^{}]*\}|[A-Za-z0-9\\]+)\s*[_^]")

_FAIL = object()
_PARSER = None
_FONT = None
_LOCK = threading.Lock()
_PREWARMED = False
_WARM_DONE = threading.Event()
_WARM_DONE.set()


class _BusyError(Exception):
    """The warm-up thread still holds the parser. This reply stays unicode."""


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
        return self.count < _FORMULA_CAP and self.spent < _TIME_CAP_S

    def add(self, seconds: float) -> None:
        self.count += 1
        self.spent += max(0.0, seconds)


class MathCache:
    """LRU of alpha masks and of recoloured images.

    The mask key is the formula, the size, and the raster scale. Colour is
    not in it, so a theme switch does not parse again.
    """

    def __init__(self, limit: int = 128) -> None:
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


def wants_image(tex: str, display: bool) -> bool:
    """True when this span should try an image instead of unicode."""
    if display:
        return True
    src = tex or ""
    if _STRUCTURE.search(src):
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
    """Import mathtext and parse one formula off the GUI thread.

    The first import is a few hundred milliseconds. A reply that arrives
    while this still holds the lock stays unicode instead of waiting.
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
                parser, font_cls = _parser()
                prop = font_cls(size=14, math_fontfamily="dejavusans")
                parser.parse(r"$x^2+\frac{a}{b}$", dpi=144, prop=prop)
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
    """Padded alpha mask, or None when mathtext cannot draw the formula."""
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


def _parser():
    global _PARSER, _FONT
    if _PARSER is None:
        os.environ.setdefault("MPLBACKEND", "Agg")
        from matplotlib import mathtext
        from matplotlib.font_manager import FontProperties

        _PARSER = mathtext.MathTextParser("agg")
        _FONT = FontProperties
    return _PARSER, _FONT


def _acquire() -> bool:
    # The suite paints a reply in the same breath it constructs the panel,
    # while the warm-up still holds the parser. Waiting there is the test
    # harness, not the window. A real reply does not wait.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return _LOCK.acquire(timeout=15)
    return _LOCK.acquire(blocking=False)


def _build_mask(tex: str, display: bool, px: int, dpr: float) -> np.ndarray | None:
    if not _acquire():
        raise _BusyError()
    try:
        rows = _raster_rows(tex, display, px, dpr)
    finally:
        _LOCK.release()
    if not rows:
        return None
    alpha, depth = _stack(rows, dpr)
    return _pad_baseline(alpha, depth, dpr, _x_height(px, _TARGET.family))


def _raster_rows(
    tex: str, display: bool, px: int, dpr: float
) -> list[tuple[np.ndarray, float]] | None:
    parser, font_cls = _parser()
    size = px * (1.15 if display else 1.0)
    prop = font_cls(size=size, math_fontfamily="dejavusans")
    dpi = 72.0 * float(dpr)
    rows: list[tuple[np.ndarray, float]] = []
    for part in _parts(tex):
        try:
            parsed = parser.parse(f"${part}$", dpi=dpi, prop=prop)
        except Exception:
            # mathtext rejects matrices, cases, and broken tex. That miss
            # is the unicode fallback, so this stays a quiet log.
            log.debug("mathtext could not draw a formula", exc_info=True)
            return None
        alpha, depth = _take_alpha(parsed)
        if alpha.size == 0 or alpha.shape[0] == 0 or alpha.shape[1] == 0:
            return None
        rows.append((alpha, depth))
    return rows or None


def _parts(tex: str) -> list[str]:
    """One mathtext string, or one per row of an aligned block.

    Matrices, cases, array, and underbrace are not rewritten. mathtext
    rejects them and the caller keeps the unicode line.
    """
    stripped = tex.strip()
    match = _ROW_ENV.fullmatch(stripped)
    if match is None:
        return [_rewrite(stripped)]
    rows: list[str] = []
    for row in re.split(r"\\\\", match.group(2)):
        cleaned = _rewrite(row.replace("&", "")).strip()
        if cleaned:
            rows.append(cleaned)
    return rows or [_rewrite(stripped)]


def _rewrite(tex: str) -> str:
    for pattern, repl in _ALIASES:
        tex = pattern.sub(repl, tex)
    return tex


def _take_alpha(parsed: object) -> tuple[np.ndarray, float]:
    image = getattr(parsed, "image", None)
    depth = float(getattr(parsed, "depth", 0) or 0)
    if image is None and isinstance(parsed, tuple) and len(parsed) >= 6:
        depth = float(parsed[4] or 0)
        image = parsed[5]
    if image is None:
        raise ValueError("mathtext returned no image")
    alpha = _as_alpha(np.asarray(image))
    return np.array(alpha, copy=True), depth


def _as_alpha(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        arr = arr[..., 3] if arr.shape[-1] == 4 else arr[..., 0]
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0)
        arr = np.rint(arr * 255.0).astype(np.uint8)
    else:
        arr = np.ascontiguousarray(arr)
    peak = int(arr.max()) if arr.size else 0
    if 0 < peak < 255:
        arr = np.rint(arr.astype(np.float32) * (255.0 / peak)).astype(np.uint8)
    return np.ascontiguousarray(arr)


def _stack(rows: list[tuple[np.ndarray, float]], dpr: float) -> tuple[np.ndarray, float]:
    if len(rows) == 1:
        return rows[0]
    gap = max(1, round(4 * dpr))
    width = max(alpha.shape[1] for alpha, _depth in rows)
    pieces: list[np.ndarray] = []
    for index, (alpha, _depth) in enumerate(rows):
        if alpha.shape[1] < width:
            extra = width - alpha.shape[1]
            left = extra // 2
            alpha = np.pad(alpha, ((0, 0), (left, extra - left)))
        pieces.append(alpha)
        if index + 1 < len(rows):
            pieces.append(np.zeros((gap, width), dtype=alpha.dtype))
    stacked = np.concatenate(pieces, axis=0)
    return stacked, stacked.shape[0] / dpr / 2.0


def _pad_baseline(alpha: np.ndarray, depth: float, dpr: float, xheight: float) -> np.ndarray:
    if alpha.size == 0 or dpr <= 0:
        return alpha
    # Depth is in device pixels. The padding was fitted at a 2x raster, where
    # that device depth was subtracted from the logical height. Keep the same
    # number when the raster scale is not 2.
    fitted_depth = float(depth) * (2.0 / dpr)
    k = _BASELINE_K * xheight
    logical_h = alpha.shape[0] / dpr
    above = logical_h - fitted_depth
    pad = (above - k) - (fitted_depth + k)
    pad_rows = round(abs(pad) * dpr)
    if pad_rows <= 0 or pad_rows > alpha.shape[0] * 3:
        return alpha
    blank = np.zeros((pad_rows, alpha.shape[1]), dtype=alpha.dtype)
    if pad > 0:
        return np.concatenate([alpha, blank], axis=0)
    return np.concatenate([blank, alpha], axis=0)


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
    raw = f"mathtext|{tex}|{int(bool(display))}|{int(px)}|{float(dpr):.2f}"
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
