"""Embedded Cesium plate for the Earth zone.

Source-checkout + astro extra only. Missing WebEngine falls back to the
Qt globe. Tokens stay in Python and ride QWebChannel — never written
into the HTML on disk.

Cesium draws the planet. Arelis still paints space and the sodium HUD.
The HUD glass is masked to chrome so wheel and drag reach Cesium.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRect, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QRegion
from PySide6.QtWidgets import QWidget

from arelis.earth.globe_stack import GlobeStack, choose_stack
from arelis.earth.lod import entity_lla
from arelis.earth.runtime import get_earth
from arelis.ui.earth_marks import heading_of

GLOBE_DIR = Path(__file__).resolve().parent / "earth_globe"
_SPACE_ENTITY_CAP = 48


def chrome_mask(panel: QWidget) -> QRegion:
    """Hit/paint region for the sodium HUD. Empty space belongs to Cesium."""
    region = QRegion()
    boxes = []
    try:
        boxes = list(panel._chrome_rects())
    except Exception:
        boxes = []
    extra = (
        getattr(panel, "_hud_box", QRect()),
        getattr(panel, "_earth_chip_box", QRect()),
        getattr(panel, "_earth_card_box", QRect()),
    )
    for box in list(boxes) + list(extra):
        if box is None or box.isEmpty():
            continue
        region = region.united(QRect(box).adjusted(-6, -6, 6, 6))
    if region.isEmpty():
        region = QRegion(QRect(8, 6, 300, 240))
    return region


class EarthHudGlass(QWidget):
    """Sodium HUD above Cesium. Only chrome eats mouse; the globe does not."""

    def __init__(self, panel: QWidget) -> None:
        super().__init__(panel)
        self._panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

    def paintEvent(self, _event) -> None:
        from arelis.physics.runtime import get_system
        from arelis.ui.panels.solar_paint import paint_overlay

        system = get_system()
        if system is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_overlay(self._panel, painter, software=False, chrome_only=True)
        self.setMask(chrome_mask(self._panel))


class GlobeBridge(QObject):
    start = Signal(str)
    setCameraJson = Signal(str)
    upsertJson = Signal(str)
    placesJson = Signal(str)
    flyJson = Signal(str)
    stackJson = Signal(str)
    showStreets = Signal(bool)
    buildingsJson = Signal(str)
    marksJson = Signal(str)

    hostReady = Signal(str)
    hostFailed = Signal(str)
    hostPicked = Signal(str)
    hostCamera = Signal(str)
    hostTiles = Signal(str)

    @Slot()
    def hello(self) -> None:
        self.start.emit(json.dumps(choose_stack().to_payload()))

    @Slot(str)
    def tilesReady(self, kind: str) -> None:
        self.hostTiles.emit(kind)

    @Slot(str)
    def failed(self, why: str) -> None:
        self.hostFailed.emit(why)

    @Slot(str)
    def picked(self, entity_id: str) -> None:
        self.hostPicked.emit(entity_id)

    @Slot(str)
    def cameraMoved(self, raw: str) -> None:
        self.hostCamera.emit(raw)

    @Slot(str)
    def ready(self, kind: str) -> None:
        self.hostReady.emit(kind)


def webengine_available() -> bool:
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except Exception:
        return False
    return True


class EarthGlobeHost(QWidget):
    """QWebEngineView child that fills the solar plate while Earth is on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ready = False
        self.failed = False
        self.kind = ""
        self._view = None
        self.bridge = GlobeBridge(self)
        self.bridge.hostReady.connect(self._on_ready)
        self.bridge.hostFailed.connect(self._on_failed)
        self.bridge.hostTiles.connect(self._on_tiles)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        if not webengine_available():
            self.failed = True
            self.kind = "native"
            return
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._view = QWebEngineView(self)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True,
        )
        self._view.loadFinished.connect(self._on_load)
        channel = QWebChannel(self._view.page())
        channel.registerObject("bridge", self.bridge)
        self._view.page().setWebChannel(channel)
        index = GLOBE_DIR / "index.html"
        self._view.setUrl(QUrl.fromLocalFile(str(index)))
        self._view.setGeometry(self.rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._view is not None:
            self._view.setGeometry(self.rect())

    def _on_ready(self, kind: str) -> None:
        self.ready = True
        self.kind = kind or choose_stack().label()
        self.push_marks()

    def _on_load(self, ok: bool) -> None:
        # Chromium emits loadFinished(False) for aborted about:blank and
        # some qrc subresources. JS reports a real Cesium miss itself.
        return

    def _on_failed(self, why: str) -> None:
        # Photoreal miss must not kill GIBS or the HUD.
        if why and why != "cesium":
            return
        self.failed = True
        self.kind = "native"
        self.hide()
        try:
            from arelis.physics.telemetry import emit

            emit("earth_globe", event="failed")
        except Exception:
            pass

    def _on_tiles(self, kind: str) -> None:
        self.ready = True
        self.kind = kind or self.kind
        self.push_marks()

    def stack(self) -> GlobeStack:
        return choose_stack()

    def push_camera(
        self,
        lat: float,
        lon: float,
        alt_m: float,
        heading: float | None = None,
        pitch: float | None = None,
    ) -> None:
        payload: dict[str, float] = {
            "lat": lat,
            "lon": lon,
            "alt_m": alt_m,
        }
        if heading is not None:
            payload["heading"] = heading
        if pitch is not None:
            payload["pitch"] = pitch
        self.bridge.setCameraJson.emit(json.dumps(payload))

    def fly_to(self, lat: float, lon: float, alt_m: float) -> None:
        self.bridge.flyJson.emit(json.dumps({"lat": lat, "lon": lon, "alt_m": alt_m}))

    def push_marks(self) -> None:
        from arelis.ui.earth_marks import atlas_data_uris

        self.bridge.marksJson.emit(json.dumps(atlas_data_uris()))

    def push_entities(self, rows: list[dict[str, Any]]) -> None:
        self.bridge.upsertJson.emit(json.dumps(rows))

    def push_places(self, rows: list[dict[str, Any]]) -> None:
        self.bridge.placesJson.emit(json.dumps(rows))

    def push_stack(self) -> None:
        self.bridge.stackJson.emit(json.dumps(self.stack().to_payload()))

    def push_streets(self, on: bool) -> None:
        self.bridge.showStreets.emit(bool(on))

    def push_buildings(self, rings: list[list[list[float]]] | None = None) -> None:
        payload = building_rows() if rings is None else rings
        self.bridge.buildingsJson.emit(json.dumps(payload))


def entity_rows() -> list[dict[str, Any]]:
    zone = get_earth()
    if zone is None or not zone.active:
        return []
    out: list[dict[str, Any]] = []
    track = zone.track_id
    ride = zone.ride_id
    band = zone.last_view.band if zone.last_view is not None else "space"
    for ent in zone.visible():
        if ent.layer == "people":
            continue
        pair = entity_lla(ent)
        if pair is None:
            continue
        lat, lon = pair
        meta = ent.meta or {}
        try:
            alt = float(meta.get("alt") or meta.get("alt_m") or 0.0)
        except (TypeError, ValueError):
            alt = 0.0
        heading = heading_of(ent)
        out.append(
            {
                "id": ent.id,
                "layer": ent.layer,
                "mark": ent.layer,
                "label": ent.label,
                "lat": lat,
                "lon": lon,
                "alt_m": alt,
                "band": band,
                "heading_deg": heading,
                "freshness": ent.freshness,
                "hot": ent.id in {track, ride},
            }
        )
    if band == "space":
        iss = [row for row in out if row["layer"] == "iss"]
        rest = [row for row in out if row["layer"] != "iss"][:_SPACE_ENTITY_CAP]
        out = iss + rest
    return out


def place_rows(band: str, lat: float, lon: float) -> list[dict[str, Any]]:
    from arelis.earth.land import places, places_dense

    if band == "space":
        return []
    found = places_dense() if band in {"near", "city"} else places()
    ranked = sorted(
        found,
        key=lambda row: (row[1] - lat) ** 2
        + (((row[2] - lon + 180.0) % 360.0) - 180.0) ** 2,
    )
    cap = 8 if band == "approach" else 18 if band == "near" else 36
    return [{"name": n, "lat": a, "lon": b} for n, a, b in ranked[:cap]]


def building_rows() -> list[list[list[float]]]:
    """City-band footprints for Cesium. Empty when the chip is off."""
    from arelis.earth.buildings import footprints_for_view

    zone = get_earth()
    if zone is None or not zone.active or not zone.buildings:
        return []
    view = zone.last_view
    if view is None or view.band != "city":
        return []
    rings = footprints_for_view(view.lat, view.lon, view.band)
    return [[[float(lat), float(lon)] for lat, lon in ring] for ring in rings]
