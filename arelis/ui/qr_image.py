"""Draw a pairing QR with the campfire palette (local, no network)."""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap

from arelis.qr import qr_modules
from arelis.ui.theme import color


def pairing_pixmap(text: str, *, scale: int = 5, pad: int = 12) -> QPixmap:
    """QR on ivory, with extra quiet margin so a camera can find the edge."""
    modules = qr_modules(text)
    n = len(modules)
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
