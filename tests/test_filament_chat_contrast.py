"""Filament chat type against the plate it is actually painted on.

Role labels ("you", "arelis"), the copy line, and notices sit on the bare
chat plate. The plate is a vertical gradient plus a gold sheen, brightest
at the top, so the same ink that is fine on the void fails up there.
Message bodies sit on the bubble wash, which is that plate with the wash
composited on top. Sizes in the transcript are 11px to 15px, regular
weight, so the bar is the body-text one (4.5:1). Large text (3:1) does
not apply: nothing in the transcript is 24px, or 18px and bold.

The spots are the label positions from a rendered Filament chat tile.
The default size is ``filament_tile.DEFAULT_SIZES["chat"]``. The taller
sizes are the same tile after a resize: the labels stay a fixed distance
from the top while the sheen at that pixel gets brighter.
"""

from __future__ import annotations

from itertools import pairwise

from arelis.ui.filament_tile import DEFAULT_SIZES
from arelis.ui.theme import COLORS, PLATE, apply_theme, color

# GlassFrame.paintEvent: sheen stops on an opaque float. accent2 at the
# top-left, accent a short way down the diagonal, clear at the far corner.
_SHEEN = ((0.0, "accent2", 80), (0.22, "accent", 36), (1.0, None, 0))

# Body-text minimum. Large-text minimum is 3.0; chat strings are smaller.
_BODY = 4.5

# (name, x as a fraction of the tile or an absolute pixel, y from the top)
_LABELS = (
    ("you", ("frac", 0.72), 60),
    ("arelis", ("px", 40), 133),
)


def _channel(v: float) -> float:
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_channel(c / 255) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(ink: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """WCAG 2 contrast ratio."""
    lo, hi = sorted((_luminance(ink), _luminance(bg)))
    return (hi + 0.05) / (lo + 0.05)


def _rgb(name: str) -> tuple[int, int, int]:
    c = color(name)
    return (c.red(), c.green(), c.blue())


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(stops: list[tuple[float, tuple[int, int, int]]], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    if t <= stops[0][0]:
        return stops[0][1]
    for (p0, c0), (p1, c1) in pairwise(stops):
        if t <= p1:
            span = p1 - p0
            return _lerp(c0, c1, (t - p0) / span if span else 0.0)
    return stops[-1][1]


def _source_over(
    src: tuple[int, int, int], alpha: int, dst: tuple[int, int, int]
) -> tuple[int, int, int]:
    a = max(0, min(255, alpha)) / 255
    return tuple(round(src[i] * a + dst[i] * (1 - a)) for i in range(3))


def plate_at(x: int, y: int, width: int, height: int) -> tuple[int, int, int]:
    """Opaque float fill at one pixel: gradient, then the gold sheen.

    Same stack as ``GlassFrame.paintEvent`` (1px inset, vertical body,
    diagonal sheen).
    """
    rw, rh = width - 2, height - 2
    stops = [(float(p), (r, g, b)) for p, (r, g, b) in PLATE["opaque"]]
    base = _gradient(stops, (y - 1) / rh)
    px, py = x - 1, y - 1
    diag = (px * rw + py * rh) / (rw * rw + rh * rh)
    prev = _SHEEN[0]
    for stop, name, alpha in _SHEEN[1:]:
        if diag <= stop:
            span = stop - prev[0]
            f = (diag - prev[0]) / span if span else 0.0
            src_name = name or prev[1]
            assert src_name is not None
            src = _rgb(src_name)
            if prev[1] is not None and name is not None:
                src = _lerp(_rgb(prev[1]), _rgb(name), f)
            mix = round(prev[2] + (alpha - prev[2]) * f)
            return _source_over(src, mix, base)
        prev = (stop, name, alpha)
    return base


def _wash(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    wash = color("bubble_wash")
    return _source_over((wash.red(), wash.green(), wash.blue()), wash.alpha(), bg)


def _code(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    fill = color("code_fill")
    return _source_over((fill.red(), fill.green(), fill.blue()), fill.alpha(), bg)


def _label_plates() -> list[tuple[str, tuple[int, int, int]]]:
    sizes = [DEFAULT_SIZES["chat"], (560, 720), (700, 1200)]
    found: list[tuple[str, tuple[int, int, int]]] = []
    for width, height in sizes:
        for name, xspec, y in _LABELS:
            kind, value = xspec
            x = int(width * value) if kind == "frac" else int(value)
            if not (1 <= x < width - 1 and 1 <= y < height - 1):
                continue
            found.append((f"{name} {width}x{height}", plate_at(x, y, width, height)))
    return found


def _worst_plate() -> tuple[int, int, int]:
    plates = _label_plates()
    assert plates, "no label spot fell inside a chat tile"
    return max(plates, key=lambda item: _luminance(item[1]))[1]


def test_filament_chat_text_meets_aa() -> None:
    apply_theme("filament")
    plate = _worst_plate()
    wash = _wash(plate)
    code_bg = _code(wash)
    # Every transcript ink, on the background that string is painted on.
    # Labels and notices are on the bare plate. Bodies, headings, quotes,
    # and links are on the wash. Code sits on code_fill over that wash.
    checks = (
        ("assistant message", "text", wash),
        ("user message", "text_dim", wash),
        ("role label", "text_dim", plate),
        ("notice", "status_amber", plate),
        ("heading", "accent", wash),
        ("inline code", "accent", code_bg),
        ("link", "accent2", wash),
    )
    failures: list[str] = []
    for name, token, bg in checks:
        ink = _rgb(token)
        ratio = contrast(ink, bg)
        if ratio < _BODY:
            failures.append(
                f"{name} ({token} #{ink[0]:02x}{ink[1]:02x}{ink[2]:02x}"
                f" on #{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}) is {ratio:.2f}, needs {_BODY}"
            )
    assert not failures, "Filament chat text is under 4.5:1:\n" + "\n".join(failures)
    # The lamp stays the filament gold. Readability is the type, not a new accent.
    assert COLORS["accent"].lower() == "#c4a06a"
