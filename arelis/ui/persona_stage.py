"""Her place in the base UI: a fixed band of the stage, under chat and tiles.

Night and Sodium seat her here (right full-height band) and keep the persona
dock as a hidden alias. Filament still hosts her in its tile until the hub
slice lands.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

BAND_SHARE = 0.28
BAND_MIN = 300
BAND_MAX = 560
# Filament hub: bottom-left corner, sized off the stage height.
HUB_SHARE = 0.45
HUB_MIN = 240
HUB_MAX = 640
# Head to toe she is about half as wide as tall, with the camera's margin.
FIGURE_ASPECT = 0.5


def region_mode(theme: str) -> str:
    """Filament puts her in the bottom-left hub; every other room uses the right band."""
    return "hub" if (theme or "").strip().lower() == "filament" else "band"


def persona_region(stage: QRect, home_band: QRect | None = None, *, mode: str = "band") -> QRect:
    """The part of the stage she owns.

    band: the right side, about 28% of the width, 300-560 px, full height.
    hub: the bottom-left corner, a head-to-toe box about 45% of the height,
    240-640 px tall, scaled down when the stage is smaller.
    In a Filament span both sit on the home desk, not the union of desks.
    The region never leaves the stage.
    """
    area = home_band.intersected(stage) if home_band is not None else QRect(stage)
    if area.isEmpty():
        area = QRect(stage)
    if mode == "hub":
        height = max(HUB_MIN, min(HUB_MAX, round(area.height() * HUB_SHARE)))
        box = fit_figure(QRect(0, 0, round(height * FIGURE_ASPECT), height), area)
        return QRect(area.left(), area.bottom() + 1 - box.height(), box.width(), box.height())
    width = min(area.width(), max(BAND_MIN, min(BAND_MAX, round(area.width() * BAND_SHARE))))
    return QRect(area.right() + 1 - width, area.top(), width, area.height())


def fit_figure(want: QRect, region: QRect) -> QRect:
    """Her head-to-toe box inside region: scaled down to fit, never cropped.

    Keeps FIGURE_ASPECT, stands on the region's bottom edge, centred across.
    """
    if region.isEmpty():
        return QRect(region.topLeft(), region.size())
    height = min(max(1, want.height()), region.height(), int(region.width() / FIGURE_ASPECT))
    width = max(1, min(region.width(), round(height * FIGURE_ASPECT)))
    left = region.left() + (region.width() - width) // 2
    return QRect(left, region.bottom() + 1 - height, width, height)


class PersonaStage(QWidget):
    """Click-through, see-through host for her panel, as a child of the stage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PersonaStage")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if parent is not None:
            parent.installEventFilter(self)
            self.follow()

    def follow(self) -> None:
        """Take her region of the parent in the active room's mode."""
        from arelis.ui.theme_tokens import active_theme

        parent = self.parentWidget()
        if parent is not None:
            self.place(parent.rect(), mode=region_mode(active_theme()))
        window = self.window()
        if in_stage(window) and hasattr(window, "_sync_panel_margins"):
            window._sync_panel_margins()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.follow()
        return False

    def host(self, panel: QWidget) -> None:
        self.layout().addWidget(panel)

    def place(self, stage: QRect, home_band: QRect | None = None, *, mode: str = "band") -> None:
        region = persona_region(stage, home_band, mode=mode)
        if region != self.geometry():
            from arelis.ui.persona_face.panel import alog

            alog(
                "resize",
                mode=mode,
                region=f"{region.x()},{region.y()},{region.width()}x{region.height()}",
            )
        self.setGeometry(region)


def in_stage(window) -> bool:
    """She sits in the base UI (not in the persona dock) in the active room."""
    return bool(getattr(window, "_persona_in_stage", False))


def _keep_dock_hidden(window, visible: bool) -> None:
    if visible and in_stage(window):
        window.persona_dock.hide()


def seat_persona(window) -> None:
    """Put her panel where the active room wants it. Safe to call again."""
    from arelis.ui.theme_tokens import active_theme

    stage = getattr(window, "persona_stage", None)
    panel = getattr(window, "persona_panel", None)
    dock = getattr(window, "persona_dock", None)
    if stage is None or panel is None or dock is None:
        return
    if not getattr(window, "_persona_alias_hooked", False):
        window._persona_alias_hooked = True
        dock.visibilityChanged.connect(lambda v, w=window: _keep_dock_hidden(w, v))
    band = region_mode(active_theme()) == "band"
    if band:
        if panel.parentWidget() is not stage:
            stage.host(panel)
        window._persona_in_stage = True
        dock.hide()
        stage.follow()
        stage.show()
        panel.show()
    else:
        window._persona_in_stage = False
        stage.hide()
        body = window.persona_host._body_host.layout()
        if panel.parentWidget() is not window.persona_host._body_host:
            body.addWidget(panel)
