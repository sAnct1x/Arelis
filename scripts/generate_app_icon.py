"""Render the Arelis app icon and pack a multi-size Windows .ico.

Motif: orbit void — warm black tile, one amber ring, a tick, a beating core.
Regenerable; the committed files under arelis/assets/ are what ships and what
shortcuts use. They live inside the package because anything outside it is absent
from an install, which is how Arelis previously shipped with no icon at all.
"""

from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arelis.ui.theme import BLOOM, FILAMENT, color

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "arelis" / "assets"
SIZES = (256, 128, 64, 48, 32, 16)

_VOID = color("bg0")
_AMBER = color("accent")
_AMBER_SOFT = color("accent2")
_GRAIN = QColor(*BLOOM["grain"])
_CORE = QColor(*FILAMENT["core"])
_TICK = QColor(*FILAMENT["tick"])


def _a(base: QColor, alpha: int) -> QColor:
    return QColor(base.red(), base.green(), base.blue(), max(0, min(255, int(alpha))))


def _paint(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    margin = max(1, round(size * 0.06))
    tile = QRect(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = size * 0.22
    cx, cy = size * 0.50, size * 0.50

    glow = QRadialGradient(QPointF(cx, cy), size * 0.52)
    glow.setColorAt(0.0, _a(_GRAIN, 72 if size >= 48 else 40))
    glow.setColorAt(0.55, _a(_AMBER, 24))
    glow.setColorAt(1.0, _a(_VOID, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawEllipse(QRectF(0, 0, size, size))

    p.setBrush(_VOID)
    p.drawRoundedRect(tile, radius, radius)

    bloom = QRadialGradient(QPointF(cx, cy), size * 0.38)
    inner_rgb = BLOOM["inner"][0][1]
    bloom.setColorAt(0.0, QColor(inner_rgb[0], inner_rgb[1], inner_rgb[2], 64 if size >= 48 else 36))
    bloom.setColorAt(0.55, _a(_AMBER, 16))
    bloom.setColorAt(1.0, _a(_VOID, 0))
    p.setBrush(bloom)
    p.drawRoundedRect(tile, radius, radius)

    ring_r = size * (0.28 if size >= 32 else 0.24)
    if size >= 24:
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((size * 0.028, 28), (max(1.0, size * 0.012), 170)):
            ring = QPen(_a(_AMBER, alpha))
            ring.setWidthF(max(1.0, width))
            ring.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ring)
            p.drawEllipse(QPointF(cx, cy), ring_r, ring_r)

    if size >= 32:
        rad = math.radians(38.0)
        tx = cx + ring_r * math.sin(rad)
        ty = cy - ring_r * math.cos(rad)
        tick_r = size * 0.055
        tick_glow = QRadialGradient(QPointF(tx, ty), tick_r * 2.4)
        tick_glow.setColorAt(0.0, _a(_TICK, 210))
        tick_glow.setColorAt(0.45, _a(_AMBER, 80))
        tick_glow.setColorAt(1.0, _a(_AMBER, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tick_glow)
        p.drawEllipse(QPointF(tx, ty), tick_r * 2.2, tick_r * 2.2)
        p.setBrush(_AMBER_SOFT)
        p.drawEllipse(QPointF(tx, ty), max(1.2, size * 0.018), max(1.2, size * 0.018))

    core_glow_r = size * (0.12 if size >= 32 else 0.16)
    core_glow = QRadialGradient(QPointF(cx, cy), core_glow_r)
    core_glow.setColorAt(0.0, _a(_CORE, 220))
    core_glow.setColorAt(0.35, _a(_AMBER, 90))
    core_glow.setColorAt(1.0, _a(_AMBER, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(core_glow)
    p.drawEllipse(QPointF(cx, cy), core_glow_r, core_glow_r)
    core_r = max(1.2, size * (0.028 if size >= 32 else 0.12))
    p.setBrush(_CORE)
    p.drawEllipse(QPointF(cx, cy), core_r, core_r)

    edge = QPen(_a(_AMBER, 70 if size >= 48 else 100))
    edge.setWidthF(max(1.0, size * 0.012))
    p.setPen(edge)
    p.setBrush(Qt.BrushStyle.NoBrush)
    inset = margin + max(1, round(size * 0.01))
    p.drawRoundedRect(
        QRectF(inset, inset, size - 2 * inset, size - 2 * inset),
        radius * 0.92,
        radius * 0.92,
    )

    p.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(path: Path, images: dict[int, bytes]) -> None:
    """Pack PNG-compressed frames into a Windows .ico (Vista+)."""
    sizes = sorted(images.keys(), reverse=True)
    count = len(sizes)
    offset = 6 + 16 * count
    entries = bytearray()
    payloads = bytearray()
    for size in sizes:
        data = images[size]
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            w,
            h,
            0,
            0,
            1,
            32,
            len(data),
            offset + len(payloads),
        )
        payloads += data
    header = struct.pack("<HHH", 0, 1, count)
    path.write_bytes(header + entries + payloads)


def main() -> int:
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
    app = QApplication.instance() or QApplication(sys.argv)

    ASSETS.mkdir(parents=True, exist_ok=True)
    png_frames: dict[int, bytes] = {}
    for size in SIZES:
        image = _paint(size)
        png_frames[size] = _png_bytes(image)
        if size == 256:
            preview = ASSETS / "arelis.png"
            image.save(str(preview), "PNG")
            print(f"wrote {preview}")

    ico_path = ASSETS / "arelis.ico"
    write_ico(ico_path, png_frames)
    print(f"wrote {ico_path} ({', '.join(f'{s}px' for s in SIZES)})")
    _ = app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
