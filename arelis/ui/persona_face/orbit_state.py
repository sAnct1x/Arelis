# ruff: noqa: N815  (Qt property and signal names are QML-facing camelCase)
"""What QuickOrbit.qml needs from the Filament sim, as one QObject (ARELIS_SURFACE=quick).

Slice 2 draws the ring, the strands, the dust and the hub threads on the GPU; in idle the
orbit tree (Iris's v11b: trunk, limbs, roots, floor link, light packets, node flares) stands
for the ring, from the anchors here. Python no longer
paints them, and nothing here runs per frame: the atmosphere tick (30 Hz, the sim's own clock)
calls update(), and each property emits only when its value changes. Geometry changes on
resize, span and hub moves; the weather on a state change; the ring's growth on its phase
changes (QML runs the 1.8 s grow itself). The one steady emit is `sync`, the sim's clock and
eased weather once a second (and on a weather change), so QML's clock stays on the clock the
Python worker paints the beads, stems and tethers with.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Property, QObject, QPointF, QRect, Signal, Slot
from PySide6.QtGui import QColor, QVector4D

from arelis.ui import filament_field as ff

LOG = logging.getLogger("arelis.avatar")
SYNC_S = 1.0
TREE_FLOOR = 0.955  # the floor the tree stands on, as a share of the height (v11b: 1328/1392)


class OrbitState(QObject):
    activeChanged = Signal()
    hubChanged = Signal()
    hasHubChanged = Signal()
    ringChanged = Signal()
    ringGrowChanged = Signal()
    ringPhaseChanged = Signal()
    spanChanged = Signal()
    weatherChanged = Signal()
    targetChanged = Signal()
    fullHalfChanged = Signal()
    listenHalfChanged = Signal()
    fadeMarginChanged = Signal()
    iceChanged = Signal()
    goldChanged = Signal()
    coreChanged = Signal()
    syncChanged = Signal()
    treeChanged = Signal()
    feetChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._values: dict[str, object] = {
            "active": False,
            "hub": QPointF(),
            "hasHub": False,
            "ring": QVector4D(),
            "ringGrow": 1.0,
            "ringPhase": "",
            "span": 1,
            "weather": "idle",
            "target": [0.0, 0.08, 0.0, 0.0, 0.0],
            "fullHalf": 0.0,
            "listenHalf": 0.0,
            "fadeMargin": 40.0,
            "ice": QColor(*ff._ICE),
            "gold": QColor(*ff._GOLD),
            "core": QColor(*ff._CORE),
            "sync": [],
            "tree": QVector4D(),
            "feet": QPointF(),
        }
        self._sync_at = 0.0
        self.emits = 0  # how many property changes went to QML (the test and the bench read it)

    def _set(self, name: str, value: object) -> None:
        if self._values.get(name) == value:
            return
        self._values[name] = value
        self.emits += 1
        getattr(self, f"{name}Changed").emit()

    def set_active(self, on: bool) -> None:
        self._set("active", bool(on))

    def update(self, field: ff.FilamentField, rect: QRect, now: float | None = None) -> None:
        """After a sim tick: push what changed. Cheap; the GPU does the per-frame work."""
        self._set("active", True)
        w = float(rect.width())
        cx, cy, rx, ry = field.ellipse(rect, settled=True)
        self._set("ring", QVector4D(cx, cy, rx, ry))
        hub = field.hub
        self._set_tree(rect, cx, cy, rx, ry, hub)
        self._set("hasHub", hub is not None)
        if hub is not None:
            self._set("hub", QPointF(hub))
        full = field._ribbon_half(w)
        self._set("fullHalf", full)
        self._set("listenHalf", min(max(field._desk_width(w) * 0.82, full * 0.55), full))
        self._set("fadeMargin", field._fade_margin(w))
        self._set("span", int(field.span))
        phase = field._ring_phase
        if phase != self._values["ringPhase"]:
            self._set("ringGrow", float(field.ring_grow))
            self._set("ringPhase", phase)
        want = ff._WEATHER[field.state]
        self._set("target", [want[k] for k in ("form", "speed", "pulse", "warm", "words")])
        weather_moved = self._values["weather"] != field.state
        self._set("weather", field.state)
        now = time.monotonic() if now is None else now
        if weather_moved or now - self._sync_at >= SYNC_S or not self._values["sync"]:
            self._sync_at = now
            self._set(
                "sync",
                [field.time, field.form, field.speed, field.pulse, field.warm, field.words],
            )

    def _set_tree(
        self, rect: QRect, cx: float, cy: float, rx: float, ry: float, hub: QPointF | None
    ) -> None:
        """The orbit tree's anchors (Iris's v11b): its base on the floor under the ring, its fork
        inside the ring, and her feet on the floor below her hub, where the floor link and the
        light packets start. The limbs, roots and packets are the GPU's (tree.vert)."""
        h = float(rect.height())
        floor = rect.top() + h * TREE_FLOOR
        base_x = cx - rx * 0.03
        fork_y = cy + max(ry * 0.55, h * 0.10)
        self._set("tree", QVector4D(base_x, floor, cx + rx * 0.02, fork_y))
        feet_x = hub.x() if hub is not None else min(cx + rx * 1.6, rect.right() - 40.0)
        self._set("feet", QPointF(feet_x, floor))

    @Slot(int)
    def reportFps(self, fps: int) -> None:
        """QML's frame counter, every 5 s: the same line the widget path logs."""
        LOG.info("[filament] orbit fps=%d", int(fps))

    active = Property(bool, lambda self: self._values["active"], notify=activeChanged)
    hub = Property(QPointF, lambda self: self._values["hub"], notify=hubChanged)
    hasHub = Property(bool, lambda self: self._values["hasHub"], notify=hasHubChanged)
    ring = Property(QVector4D, lambda self: self._values["ring"], notify=ringChanged)
    ringGrow = Property(float, lambda self: self._values["ringGrow"], notify=ringGrowChanged)
    ringPhase = Property(str, lambda self: self._values["ringPhase"], notify=ringPhaseChanged)
    ringGrowSeconds = Property(float, lambda self: ff.RING_GROW_S, constant=True)
    span = Property(int, lambda self: self._values["span"], notify=spanChanged)
    weather = Property(str, lambda self: self._values["weather"], notify=weatherChanged)
    target = Property(list, lambda self: self._values["target"], notify=targetChanged)
    fullHalf = Property(float, lambda self: self._values["fullHalf"], notify=fullHalfChanged)
    listenHalf = Property(float, lambda self: self._values["listenHalf"], notify=listenHalfChanged)
    fadeMargin = Property(float, lambda self: self._values["fadeMargin"], notify=fadeMarginChanged)
    ice = Property(QColor, lambda self: self._values["ice"], notify=iceChanged)
    gold = Property(QColor, lambda self: self._values["gold"], notify=goldChanged)
    core = Property(QColor, lambda self: self._values["core"], notify=coreChanged)
    sync = Property(list, lambda self: self._values["sync"], notify=syncChanged)
    tree = Property(QVector4D, lambda self: self._values["tree"], notify=treeChanged)
    feet = Property(QPointF, lambda self: self._values["feet"], notify=feetChanged)
