"""Filament plates: own windows, live opacity. Not layered per-pixel."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QLabel,
    QMenu,
    QSlider,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from arelis.config import merge_local_config

DEFAULT_OPACITY = 0.80
_MIN = 0.15
_MAX = 1.00
_SEED = (68, 52)
_TRAIL_MS = 180
_GROW_MS = 520
DEFAULT_SIZES: dict[str, tuple[int, int]] = {
    "thinking": (320, 260),
    "files": (340, 280),
    "history": (300, 360),
    "chat": (380, 400),
    "days": (360, 340),
    "camera": (340, 280),
    "notify": (340, 280),
    "contacts": (320, 260),
    "reality": (420, 320),
}


def clamp_opacity(value: float) -> float:
    return max(_MIN, min(_MAX, float(value)))


def load_opacities(config: dict) -> dict[str, float]:
    raw = ((config.get("ui") or {}).get("filament_opacity") or {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, val in raw.items():
        try:
            out[str(key)] = clamp_opacity(float(val))
        except (TypeError, ValueError):
            continue
    return out


def apply_tile_opacity(widget: QWidget, value: float) -> None:
    widget.setWindowOpacity(clamp_opacity(value))


def add_opacity_action(
    menu: QMenu, widget: QWidget, name: str, store: dict[str, float]
) -> None:
    """Live slider. The plate updates as the thumb moves."""
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(12, 8, 12, 10)
    lay.setSpacing(6)
    label = QLabel("translucency")
    label.setObjectName("FilamentFloat")
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(int(_MIN * 100), int(_MAX * 100))
    current = clamp_opacity(store.get(name, widget.windowOpacity() or DEFAULT_OPACITY))
    slider.setValue(round(current * 100))

    persist = QTimer(host)
    persist.setSingleShot(True)
    persist.setInterval(400)

    def _write() -> None:
        merge_local_config({"ui": {"filament_opacity": {name: store.get(name, current)}}})

    persist.timeout.connect(_write)

    def _slide(v: int) -> None:
        alpha = clamp_opacity(v / 100.0)
        store[name] = alpha
        apply_tile_opacity(widget, alpha)
        persist.start()

    slider.valueChanged.connect(_slide)
    lay.addWidget(label)
    lay.addWidget(slider)
    action = QWidgetAction(menu)
    action.setDefaultWidget(host)
    menu.addAction(action)


def popup_tile_opacity(widget: QWidget, name: str, store: dict[str, float]) -> None:
    """Right-click hatch: slide the plate's see-through in real time."""
    menu = QMenu(widget)
    menu.setObjectName("FilamentOpacityMenu")
    add_opacity_action(menu, widget, name, store)
    menu.exec(QCursor.pos())


def bind_tile_opacity(widget: QWidget, name: str, store: dict[str, float]) -> None:
    widget._filament_opacity_store = store
    widget._filament_opacity_name = name
    apply_tile_opacity(widget, store.get(name, DEFAULT_OPACITY))
    if getattr(widget, "_filament_opacity_bound", False):
        return
    widget._filament_opacity_bound = True
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    widget.customContextMenuRequested.connect(
        lambda _pos, w=widget, n=name: popup_tile_opacity(w, n, store)
    )


def load_tile_origins(config: dict) -> dict[str, tuple[int, int]]:
    raw = ((config.get("ui") or {}).get("filament_tile_pos") or {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[int, int]] = {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        try:
            out[str(key)] = (int(val["x"]), int(val["y"]))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def remember_tile_origin(
    widget: QWidget, name: str, store: dict[str, tuple[int, int]]
) -> None:
    geo = widget.frameGeometry()
    pos = (int(geo.x()), int(geo.y()))
    store[name] = pos
    merge_local_config({"ui": {"filament_tile_pos": {name: {"x": pos[0], "y": pos[1]}}}})


def origin_on_a_desk(x: int, y: int, width: int, height: int) -> bool:
    """True if any work area still touches this plate. Unplugged = forget."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return False
    dest = QRect(int(x), int(y), max(1, int(width)), max(1, int(height)))
    for screen in app.screens():
        if screen.availableGeometry().intersects(dest):
            return True
    return False


def load_tile_sizes(config: dict) -> dict[str, tuple[int, int]]:
    raw = ((config.get("ui") or {}).get("filament_tile_size") or {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[int, int]] = {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        try:
            width = max(240, min(720, int(val.get("w", 0))))
            height = max(180, min(800, int(val.get("h", 0))))
        except (TypeError, ValueError):
            continue
        out[str(key)] = (width, height)
    return out


def tile_grow_rects(origin: QPoint, size: tuple[int, int]) -> tuple[QRect, QRect]:
    """Seed at the title, then the plate. Same origin so it grows out of the trail."""
    width = max(240, int(size[0]))
    height = max(180, int(size[1]))
    seed = QRect(int(origin.x()), int(origin.y()), _SEED[0], _SEED[1])
    dest = QRect(int(origin.x()), int(origin.y()), width, height)
    return seed, dest


def play_tile_grow(
    widget: QWidget,
    origin: QPoint,
    size: tuple[int, int],
    *,
    opacity: float = DEFAULT_OPACITY,
) -> None:
    """Trail first, then the plate grows out of that end. Not a pop."""
    seed, dest = tile_grow_rects(origin, size)
    prior = getattr(widget, "_filament_grow_group", None)
    if prior is not None:
        prior.stop()
    widget._filament_growing = True
    widget.setMinimumSize(_SEED[0], _SEED[1])
    widget.hide()
    widget.setGeometry(seed)
    apply_tile_opacity(widget, max(0.18, clamp_opacity(opacity) * 0.28))
    widget.show()
    widget.raise_()

    def _start() -> None:
        if widget.isHidden():
            widget._filament_growing = False
            return
        geo = QPropertyAnimation(widget, b"geometry", widget)
        geo.setDuration(_GROW_MS)
        geo.setEasingCurve(QEasingCurve.Type.OutCubic)
        geo.setStartValue(QRect(widget.geometry()))
        geo.setEndValue(dest)
        fade = QPropertyAnimation(widget, b"windowOpacity", widget)
        fade.setDuration(_GROW_MS)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.setStartValue(float(widget.windowOpacity()))
        fade.setEndValue(clamp_opacity(opacity))
        group = QParallelAnimationGroup(widget)
        group.addAnimation(geo)
        group.addAnimation(fade)

        def _done() -> None:
            widget._filament_growing = False
            widget.setMinimumSize(240, 180)
            widget.setGeometry(dest)
            apply_tile_opacity(widget, opacity)
            filt = getattr(widget, "_filament_size_filter", None)
            if filt is not None:
                filt._timer.start()

        group.finished.connect(_done)
        widget._filament_grow_group = group
        group.start()

    QTimer.singleShot(_TRAIL_MS, _start)


def apply_tile_size(widget: QWidget, name: str, store: dict[str, tuple[int, int]]) -> None:
    width, height = store.get(name) or DEFAULT_SIZES.get(name, (320, 280))
    width = max(240, min(720, int(width)))
    height = max(180, min(800, int(height)))
    widget.setMaximumSize(720, 800)
    widget.resize(width, height)


def remember_tile_size(
    widget: QWidget, name: str, store: dict[str, tuple[int, int]]
) -> None:
    size = (max(240, min(720, widget.width())), max(180, min(800, widget.height())))
    store[name] = size
    merge_local_config({"ui": {"filament_tile_size": {name: {"w": size[0], "h": size[1]}}}})


class _GeomRemember(QObject):
    def __init__(
        self,
        widget: QWidget,
        name: str,
        sizes: dict[str, tuple[int, int]],
        origins: dict[str, tuple[int, int]],
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._name = name
        self._sizes = sizes
        self._origins = origins
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._write)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self._widget and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            if getattr(self._widget, "_filament_growing", False):
                return False
            self._timer.start()
        return False

    def _write(self) -> None:
        from arelis.ui.theme import active_theme

        if active_theme() != "filament":
            return
        remember_tile_size(self._widget, self._name, self._sizes)
        remember_tile_origin(self._widget, self._name, self._origins)


def bind_tile_size(
    widget: QWidget,
    name: str,
    store: dict[str, tuple[int, int]],
    origins: dict[str, tuple[int, int]] | None = None,
) -> None:
    if getattr(widget, "_filament_size_bound", False):
        return
    widget._filament_size_bound = True
    parked = origins if origins is not None else getattr(
        widget, "_filament_origin_store", {}
    )
    filt = _GeomRemember(widget, name, store, parked)
    widget.installEventFilter(filt)
    widget._filament_size_filter = filt
    widget._filament_origin_store = parked


def flush_tile_geom(widget: QWidget) -> None:
    """Write size and origin now. Close before the debounce would lose them."""
    filt = getattr(widget, "_filament_size_filter", None)
    if filt is None:
        return
    filt._timer.stop()
    filt._write()
