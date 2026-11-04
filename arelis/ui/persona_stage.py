"""Her place in the base UI, under chat and tiles.

With WebEngine, Night and Sodium seat her in the right full-height band, head to
toe and scaled to fit. In Filament, and in every room Quick 3D hosts her, she is
the base layer: her view fills the stage (the home desk in a span) and she stands
right of centre (FIGURE_X), full height; the chat, and in Filament the orbit,
reality and tiles, live left of her figure zone (in Filament they grow out of her
centre, set_hub). The persona dock is kept only as a hidden alias.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from arelis.ui.theme_tokens import SHELL

BAND_SHARE = 0.28
BAND_MIN = 300
BAND_MAX = 560
# The chat column keeps at least this much of the stage; her band gives way first,
# down to BAND_FIT_MIN, the narrowest band her head-to-toe box still reads in.
CHAT_MIN = 380
BAND_FIT_MIN = 180
# The stage's own padding around the chat column, beyond the column's minimum.
CHAT_PAD = 2 * SHELL["outer"]
# Filament: her centre across the stage, and where her figure zone starts (the
# orbit and tiles stay left of it).
FIGURE_X = 0.82
FIGURE_LEFT = 0.66
# Filament: her height as a share of her full head-to-toe frame. Her soles stay on the
# floor line and she gets headroom, so she reads as standing beside the tree. Everything
# tied to her size (the camera, her hub, the floor link at her feet) derives from this.
FIGURE_SCALE = 0.85


def base_layer(theme: str) -> bool:
    """Her view is the stage's base layer: Filament, and every room Quick 3D hosts her in.

    The WebEngine host keeps Night and Sodium in the right band. Quick 3D's look carries
    its own backdrop haze, which in a band ends on the band's edges: a box.
    """
    from arelis.ui.persona_face import qq3d_avatar

    room = (theme or "").strip().lower()
    return room == "filament" or qq3d_avatar.wanted(room)


def figure_x(theme: str) -> float:
    """Where her centre stands across her view, 0..1."""
    return FIGURE_X if base_layer(theme) else 0.5


def figure_scale(theme: str) -> float:
    """Her height in her view, as a share of head to toe: smaller in Filament only."""
    return FIGURE_SCALE if (theme or "").strip().lower() == "filament" else 1.0


def figure_hub_y(top: float, height: float, scale: float) -> float:
    """Her centre's height in a view `height` tall: half her height above the soles,
    which stay on the view's bottom whatever her scale."""
    return top + height * (1.0 - scale / 2.0)


def figure_zone(region: QRect) -> QRect:
    """Base layer: the part of her full-stage region her figure takes (right of FIGURE_LEFT)."""
    left = region.left() + round(region.width() * FIGURE_LEFT)
    return QRect(left, region.top(), region.right() + 1 - left, region.height())


def persona_region(
    stage: QRect,
    home_band: QRect | None = None,
    *,
    chat_min: int = CHAT_MIN,
    base_layer: bool = False,
) -> QRect:
    """The part of the stage she owns.

    base_layer (Filament): all of it, or the home desk in a span.

    The right side, about 28% of the width, 300-560 px, full height.
    On a narrow stage the band shrinks first so the chat keeps chat_min
    (CHAT_MIN, or more when the composer row needs more),
    but never below BAND_FIT_MIN (she scales down head to toe, never cropped).
    In a Filament span it sits on the home desk, not the union of desks.
    The region never leaves the stage.
    """
    area = home_band.intersected(stage) if home_band is not None else QRect(stage)
    if area.isEmpty():
        area = QRect(stage)
    if base_layer:
        return area
    width = max(BAND_MIN, min(BAND_MAX, round(area.width() * BAND_SHARE)))
    width = max(BAND_FIT_MIN, min(width, area.width() - max(CHAT_MIN, chat_min)))
    width = min(area.width(), width)
    return QRect(area.right() + 1 - width, area.top(), width, area.height())


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
        self._batch = 0

        if parent is not None:
            parent.installEventFilter(self)
            self.follow()

    def begin_batch(self) -> None:
        """A room switch is under way: hold her region until end_batch.

        The switch hides chrome bars and slims the title bar one at a time, so
        the stage stepped through four sizes (273x546 .. 313x626 over 170 ms)
        and her view took every one. During a batch follow() only waits.
        """
        self._batch += 1

    def end_batch(self) -> None:
        """The switch is done: let the layout settle once, then take one region."""
        self._batch = max(0, self._batch - 1)
        if self._batch:
            return
        from PySide6.QtWidgets import QApplication

        top = self.window()
        for _ in range(8):
            before = self.parentWidget().size() if self.parentWidget() is not None else None
            if top is not None and top.layout() is not None:
                top.layout().activate()
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            after = self.parentWidget().size() if self.parentWidget() is not None else None
            if after == before:
                break
        self.follow()

    def follow(self) -> None:
        """Take her band of the parent; in Filament the field grows out of her centre."""
        if self._batch:
            return
        from arelis.ui.theme_tokens import active_theme

        parent = self.parentWidget()
        window = self.window()
        if parent is not None:
            self.place(
                parent.rect(),
                self._home_band(),
                chat_min=_chat_min(window),
                base_layer=base_layer(active_theme()),
            )
        field = getattr(window, "_filament", None)
        if field is not None and hasattr(field, "set_hub"):
            hub = None
            band_left = None
            if active_theme() == "filament" and parent is not None:
                g = self.geometry()
                at = QPointF(
                    g.left() + g.width() * FIGURE_X,
                    figure_hub_y(g.top(), g.height(), FIGURE_SCALE),
                )
                hub = QPointF(parent.mapTo(window, at.toPoint()))
                band_left = parent.mapTo(window, figure_zone(g).topLeft()).x()
            field.set_hub(hub, band_left)
            if hub is not None and getattr(window, "filament", None) is not None:
                from arelis.ui.filament_desk import filament_tiles_clear_hub

                filament_tiles_clear_hub(window)
        if in_stage(window) and hasattr(window, "_sync_panel_margins"):
            window._sync_panel_margins()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self.parentWidget():
            return False
        if event.type() == QEvent.Type.Resize:
            self.follow()
        elif event.type() == QEvent.Type.LayoutRequest and self._chat_need_moved():
            # The composer row grew its minimum (the workbench plate opened):
            # the band gives way now, not on the next window resize.
            self.follow()
        return False

    def _chat_need_moved(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return False
        from arelis.ui.theme_tokens import active_theme

        want = persona_region(
            parent.rect(),
            self._home_band(),
            chat_min=_chat_min(self.window()),
            base_layer=base_layer(active_theme()),
        )
        return want != self.geometry()

    def zone(self) -> QRect:
        """Where her figure stands, in parent coordinates (Filament: her figure zone)."""
        from arelis.ui.theme_tokens import active_theme

        if base_layer(active_theme()):
            return figure_zone(self.geometry())
        return QRect(self.geometry())

    def right_reserve(self) -> int:
        """How much of the parent's right side is hers (the chat or desk stops short of it)."""
        parent = self.parentWidget()
        width = parent.width() if parent is not None else self.geometry().right() + 1
        return max(0, width - self.zone().left())

    def _home_band(self) -> QRect | None:
        """The home desk in a Filament span of 2 or 3 desks, in stage coordinates."""
        from arelis.ui.theme_tokens import active_theme

        window, parent = self.window(), self.parentWidget()
        home = getattr(window, "_filament_home_band", None)
        if home is None or parent is None or active_theme() != "filament":
            return None
        return QRect(parent.mapFrom(window, home.topLeft()), home.size())

    def host(self, panel: QWidget) -> None:
        self.layout().addWidget(panel)

    def place(
        self,
        stage: QRect,
        home_band: QRect | None = None,
        *,
        chat_min: int = CHAT_MIN,
        base_layer: bool = False,
    ) -> None:
        region = persona_region(stage, home_band, chat_min=chat_min, base_layer=base_layer)
        if region != self.geometry():
            from arelis.ui.persona_face.panel import alog

            alog(
                "resize",
                region=f"{region.x()},{region.y()},{region.width()}x{region.height()}",
            )
        self.setGeometry(region)


def _chat_min(window) -> int:
    """What the chat column needs: CHAT_MIN, or its composer row's minimum."""
    conv = getattr(window, "conversation", None)
    if conv is None or not hasattr(conv, "minimumSizeHint"):
        return CHAT_MIN
    return max(CHAT_MIN, conv.minimumSizeHint().width() + CHAT_PAD)


def in_stage(window) -> bool:
    """She sits in the base UI (not in the persona dock) in the active room."""
    return bool(getattr(window, "_persona_in_stage", False))


def seat_persona(window) -> None:
    """Seat her panel in the stage's band. Safe to call again."""
    stage = getattr(window, "persona_stage", None)
    panel = getattr(window, "persona_panel", None)
    if stage is None or panel is None:
        return
    if panel.parentWidget() is not stage:
        stage.host(panel)
    window._persona_in_stage = True
    stage.follow()
    stage.show()
    panel.show()


def band_seated(window) -> bool:
    """She takes the right band, so the chat has to stop short of it."""
    return in_stage(window)
