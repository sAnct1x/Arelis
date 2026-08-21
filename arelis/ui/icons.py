from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from arelis.ui.theme import color

# The two voice controls are drawn, not shipped as assets, for the same reason
# the send flare is: an imported glyph set brings its own weight and corner
# radius and reads as pasted onto the glass rather than lit behind it.


def _tint(name: str, alpha: int) -> QColor:
    value = color(name)
    value.setAlpha(alpha)
    return value


_ACCENT = _tint("accent", 230)
_ACCENT_DIM = _tint("accent2", 200)
_LIVE = _tint("accent", 235)
_CHROME = _tint("text", 180)
_CHROME_DIM = _tint("text_dim", 200)
_STATUS_WHITE = _tint("status_white", 230)
_HALO = _tint("accent", 28)
_HALO_SOFT = _tint("accent", 24)
_SPARK = _tint("status_white", 210)


def _chrome_canvas(size: int) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pm, p


def window_minimize_icon(size: int = 16) -> QIcon:
    """Minimal line: horizontal dash."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_CHROME_DIM)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    y = size * 0.55
    p.drawLine(QPointF(size * 0.28, y), QPointF(size * 0.72, y))
    p.end()
    return QIcon(pm)


def window_maximize_icon(size: int = 16, *, restore: bool = False) -> QIcon:
    """Minimal line square (or overlapped squares for restore)."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_CHROME_DIM)
    pen.setWidthF(1.25)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if restore:
        # Back square (top-right)
        p.drawRect(QRectF(size * 0.34, size * 0.22, size * 0.38, size * 0.38))
        # Front square (bottom-left), drawn second so it reads on top
        p.drawRect(QRectF(size * 0.24, size * 0.34, size * 0.38, size * 0.38))
    else:
        p.drawRect(QRectF(size * 0.28, size * 0.28, size * 0.44, size * 0.44))
    p.end()
    return QIcon(pm)


def window_close_icon(size: int = 16) -> QIcon:
    """Minimal line X."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_CHROME)
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(size * 0.30, size * 0.30), QPointF(size * 0.70, size * 0.70))
    p.drawLine(QPointF(size * 0.70, size * 0.30), QPointF(size * 0.30, size * 0.70))
    p.end()
    return QIcon(pm)


def signal_flare_icon(size: int = 28) -> QIcon:
    """Send affordance: a quiet constellation chevron, not a generic paper plane."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Soft glow disc
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_HALO)
    p.drawEllipse(QRect(2, 2, size - 4, size - 4))

    # Three-star chevron pointing right-up (a "flare" leaving orbit)
    stars = [
        (0.28, 0.62, 1.6),
        (0.48, 0.48, 2.0),
        (0.70, 0.32, 1.5),
    ]
    p.setBrush(_ACCENT)
    for x, y, r in stars:
        p.drawEllipse(QPointF(size * x, size * y), r, r)

    # Thin vector trail
    pen = QPen(_ACCENT_DIM)
    pen.setWidthF(1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(
        QPointF(size * 0.30, size * 0.66),
        QPointF(size * 0.74, size * 0.28),
    )
    # Tiny tip spark
    p.setBrush(_STATUS_WHITE)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(size * 0.76, size * 0.26), 1.4, 1.4)
    p.end()
    return QIcon(pm)


def microphone_icon(size: int = 22, *, live: bool = False, pulse: float = 1.0) -> QIcon:
    """Dictate affordance: a capsule in a listening cradle.

    The live variant brightens the same amber as the rest of the void.
    ``pulse`` (0-1+) scales the glow disc while live so the control can breathe.
    """
    tint = _LIVE if live else _ACCENT
    glow = int((34 if live else 24) * max(0.35, min(1.35, pulse)))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(tint.red(), tint.green(), tint.blue(), glow))
    p.drawEllipse(QRect(2, 2, size - 4, size - 4))

    capsule = QRectF(size * 0.38, size * 0.20, size * 0.24, size * 0.40)
    p.setBrush(tint)
    p.drawRoundedRect(capsule, capsule.width() / 2, capsule.width() / 2)

    pen = QPen(QColor(tint.red(), tint.green(), tint.blue(), 205))
    pen.setWidthF(1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cradle = QRectF(size * 0.29, size * 0.34, size * 0.42, size * 0.38)
    # Half arc opening downward: the cradle under the capsule.
    p.drawArc(cradle, 180 * 16, 180 * 16)
    p.drawLine(QPointF(size * 0.50, size * 0.72), QPointF(size * 0.50, size * 0.82))
    p.end()
    return QIcon(pm)


def paperclip_icon(size: int = 22) -> QIcon:
    """Attach affordance: a simple clip, not an emoji."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_HALO_SOFT)
    p.drawEllipse(QRect(2, 2, size - 4, size - 4))
    pen = QPen(_ACCENT)
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Vertical loop with a hook at the top.
    p.drawRoundedRect(
        QRectF(size * 0.38, size * 0.22, size * 0.22, size * 0.48),
        size * 0.11,
        size * 0.11,
    )
    p.drawArc(
        QRectF(size * 0.30, size * 0.14, size * 0.38, size * 0.28),
        20 * 16,
        160 * 16,
    )
    p.end()
    return QIcon(pm)


def conversation_icon(size: int = 22, *, live: bool = False, pulse: float = 1.0) -> QIcon:
    """Hands-free affordance: two arcs answering each other.

    Distinct from the microphone on purpose. Dictation is one person talking
    into a box; conversation is an exchange, so the glyph is a pair.
    """
    tint = _LIVE if live else _ACCENT
    glow = int((34 if live else 24) * max(0.35, min(1.85, pulse)))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(tint.red(), tint.green(), tint.blue(), glow))
    p.drawEllipse(QRect(2, 2, size - 4, size - 4))

    pen = QPen(tint)
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    # Left arc opens right, right arc opens left: two speakers facing.
    p.drawArc(QRectF(size * 0.16, size * 0.22, size * 0.40, size * 0.46), 70 * 16, 220 * 16)
    pen.setColor(_ACCENT_DIM if not live else tint)
    p.setPen(pen)
    p.drawArc(QRectF(size * 0.44, size * 0.32, size * 0.40, size * 0.46), 250 * 16, 220 * 16)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_SPARK)
    p.drawEllipse(QPointF(size * 0.50, size * 0.50), 1.3, 1.3)
    p.end()
    return QIcon(pm)


# Workspace chrome is drawn in the same line language as the send flare,
# not imported from a glyph set that would sit on the glass at the wrong weight.


def _draw_folder_body(p: QPainter, size: int, pen: QPen) -> None:
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(size * 0.22, size * 0.30, size * 0.28, size * 0.16), 1.6, 1.6)
    p.drawRoundedRect(QRectF(size * 0.18, size * 0.40, size * 0.64, size * 0.40), 2.2, 2.2)


def folder_plus_icon(size: int = 16) -> QIcon:
    """Add an existing folder as a project."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    _draw_folder_body(p, size, pen)
    p.drawLine(QPointF(size * 0.50, size * 0.50), QPointF(size * 0.50, size * 0.70))
    p.drawLine(QPointF(size * 0.40, size * 0.60), QPointF(size * 0.60, size * 0.60))
    p.end()
    return QIcon(pm)


def folder_new_icon(size: int = 16) -> QIcon:
    """Create a folder and add it as a project."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    _draw_folder_body(p, size, pen)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_SPARK)
    p.drawEllipse(QPointF(size * 0.72, size * 0.30), 1.6, 1.6)
    p.end()
    return QIcon(pm)


def folder_minus_icon(size: int = 16) -> QIcon:
    """Remove a project from the workspace (files stay on disk)."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    _draw_folder_body(p, size, pen)
    p.drawLine(QPointF(size * 0.38, size * 0.60), QPointF(size * 0.62, size * 0.60))
    p.end()
    return QIcon(pm)


def folder_up_icon(size: int = 16) -> QIcon:
    """Go up one folder in browse."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(size * 0.50, size * 0.28), QPointF(size * 0.50, size * 0.74))
    p.drawLine(QPointF(size * 0.50, size * 0.28), QPointF(size * 0.32, size * 0.46))
    p.drawLine(QPointF(size * 0.50, size * 0.28), QPointF(size * 0.68, size * 0.46))
    p.end()
    return QIcon(pm)


def refresh_icon(size: int = 16) -> QIcon:
    """Reload the browse list."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(size * 0.24, size * 0.24, size * 0.52, size * 0.52), 50 * 16, 260 * 16)
    p.drawLine(QPointF(size * 0.68, size * 0.28), QPointF(size * 0.80, size * 0.22))
    p.drawLine(QPointF(size * 0.68, size * 0.28), QPointF(size * 0.72, size * 0.42))
    p.end()
    return QIcon(pm)


def file_open_icon(size: int = 16) -> QIcon:
    """Open a file into the editor."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.35)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(size * 0.26, size * 0.20, size * 0.40, size * 0.56), 1.8, 1.8)
    p.drawLine(QPointF(size * 0.48, size * 0.20), QPointF(size * 0.66, size * 0.36))
    p.drawLine(QPointF(size * 0.48, size * 0.36), QPointF(size * 0.66, size * 0.36))
    p.end()
    return QIcon(pm)


def file_save_icon(size: int = 16) -> QIcon:
    """Save the editor buffer to disk."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(size * 0.50, size * 0.22), QPointF(size * 0.50, size * 0.58))
    p.drawLine(QPointF(size * 0.50, size * 0.58), QPointF(size * 0.36, size * 0.44))
    p.drawLine(QPointF(size * 0.50, size * 0.58), QPointF(size * 0.64, size * 0.44))
    p.drawLine(QPointF(size * 0.28, size * 0.74), QPointF(size * 0.72, size * 0.74))
    p.end()
    return QIcon(pm)


def browse_folder_icon(size: int = 14) -> QIcon:
    """List decoration for a directory."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT_DIM)
    pen.setWidthF(1.2)
    _draw_folder_body(p, size, pen)
    p.end()
    return QIcon(pm)


def browse_file_icon(size: int = 14) -> QIcon:
    """List decoration for a file."""
    pm, p = _chrome_canvas(size)
    pen = QPen(_ACCENT_DIM)
    pen.setWidthF(1.2)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(size * 0.30, size * 0.20, size * 0.40, size * 0.58), 1.5, 1.5)
    p.drawLine(QPointF(size * 0.52, size * 0.20), QPointF(size * 0.70, size * 0.36))
    p.drawLine(QPointF(size * 0.52, size * 0.36), QPointF(size * 0.70, size * 0.36))
    p.end()
    return QIcon(pm)
