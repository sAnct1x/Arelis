"""Draw a pairing QR with the campfire palette (local, no network)."""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap

from arelis.qr import qr_modules
from arelis.ui.theme import color


def pairing_pixmap(
    text: str,
    *,
    scale: int = 5,
    pad: int = 12,
    max_side: int | None = None,
) -> QPixmap:
    """QR on ivory, with extra quiet margin so a camera can find the edge.

    ``max_side`` picks a smaller whole-module scale so the code stays sharp
    and still fits the page. A smooth shrink would blur the modules.
    """
    modules = qr_modules(text)
    n = len(modules)
    if max_side is not None and n:
        room = max_side - 2 * pad
        if room > 0:
            scale = max(2, min(scale, room // n))
    inner = n * scale
    side = inner + 2 * pad
    img = QImage(side, side, QImage.Format.Format_RGB32)
    dark = color("bg0")
    light = color("text")
    img.fill(light)
    for r in range(n):
        for c in range(n):
            pixel = dark if modules[r][c] else light
            x0 = pad + c * scale
            y0 = pad + r * scale
            for y in range(scale):
                for x in range(scale):
                    img.setPixelColor(x0 + x, y0 + y, pixel)
    return QPixmap.fromImage(img)
