"""Walk the live Earth globe and dump screen grabs.

Cesium is skipped under pytest. This script is the eyes: chooser, solar,
enter Earth, bands, wheel, leave. Writes PNGs to .tmp-reality-walk-live/
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "--city-cluster" not in sys.argv:
    os.environ["ARELIS_SOLAR_GL"] = "1"

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
except Exception as exc:
    print(f"webengine import failed: {exc}", flush=True)

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

DEST = ROOT / ".tmp-reality-marks"


def _pump(app: QApplication, ms: int = 50) -> None:
    app.processEvents()
    if ms:
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) * 1000 < ms:
            app.processEvents()


def _grab_screen(app: QApplication, window, name: str) -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    top = window.window()
    top.show()
    top.raise_()
    top.activateWindow()
    app.processEvents()
    screen = top.screen() or app.primaryScreen()
    pix = screen.grabWindow(int(top.winId()))
    dest = DEST / name
    pix.save(str(dest), "PNG")
    widget = window.grab()
    widget.save(str(DEST / f"w-{name}"), "PNG")
    print(f"wrote {dest}  {pix.width()}x{pix.height()}", flush=True)
    return dest


def _key(panel, key: int) -> None:
    panel.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    )
    panel.keyReleaseEvent(
        QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier)
    )


def _write_atlas(app: QApplication) -> Path:
    from PySide6.QtGui import QColor, QPainter, QPixmap

    from arelis.earth.entity import LAYER_IDS
    from arelis.ui.earth_marks import SOLAR_KINDS, mark_image
    from arelis.ui.theme import color

    cols = 5
    kinds = list(LAYER_IDS) + list(SOLAR_KINDS)
    rows = (len(kinds) + cols - 1) // cols
    cell = 72
    pix = QPixmap(cols * cell, rows * cell)
    pix.fill(QColor(color("bg0")))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(color("text_dim")))
    for i, kind in enumerate(kinds):
        x = (i % cols) * cell
        y = (i // cols) * cell
        img = mark_image(kind, band="city")
        painter.drawImage(x + 20, y + 8, img)
        painter.drawText(x + 4, y + 64, kind)
    painter.end()
    DEST.mkdir(parents=True, exist_ok=True)
    dest = DEST / "00-mark-atlas.png"
    pix.save(str(dest), "PNG")
    print(f"wrote {dest}  {pix.width()}x{pix.height()}", flush=True)
    return dest


def _write_city_atlas(app: QApplication) -> Path:
    """Large city-band contact sheet. mark_image(..., band='city') at ATLAS_PX."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap

    from arelis.earth.entity import LAYER_IDS
    from arelis.ui.earth_marks import ATLAS_PX, SOLAR_KINDS, mark_image
    from arelis.ui.theme import color

    headings = (0.0, 45.0, 90.0, 180.0)
    kinds = list(LAYER_IDS) + list(SOLAR_KINDS)
    extras = [("flights", h) for h in headings]
    cells = [(k, None) for k in kinds] + extras
    cols = 5
    rows = (len(cells) + cols - 1) // cols
    cell = max(160, ATLAS_PX * 5)
    pix = QPixmap(cols * cell, rows * cell)
    pix.fill(QColor(color("bg0")))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(color("text_dim")))
    glyph = max(ATLAS_PX * 4, 96)
    for i, (kind, heading) in enumerate(cells):
        x = (i % cols) * cell
        y = (i // cols) * cell
        img = mark_image(kind, band="city", heading_deg=heading, size=glyph)
        ox = x + (cell - img.width()) // 2
        oy = y + 12
        painter.drawImage(ox, oy, img)
        label = kind if heading is None else f"flights {int(heading)}"
        painter.drawText(
            x + 6,
            y + cell - 10,
            cell - 12,
            16,
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
    painter.end()
    DEST.mkdir(parents=True, exist_ok=True)
    dest = DEST / "00-mark-atlas-city.png"
    pix.save(str(dest), "PNG")
    print(f"wrote {dest}  {pix.width()}x{pix.height()}  glyph={glyph}px", flush=True)
    return dest


def _seed_marks(zone, lat: float = 39.78, lon: float = -89.65) -> None:
    from arelis.earth.entity import LAYER_IDS, Entity
    from arelis.earth.frames import lla_to_ecef

    cls_of = {
        "flights": "aircraft",
        "drones": "aircraft",
        "military": "aircraft",
        "vessels": "vessel",
        "satellites": "satellite",
        "iss": "station",
        "cameras": "camera",
        "quakes": "quake",
        "fires": "fire",
        "people": "person",
        "sites": "site",
        "radio": "rf",
        "weather": "weather",
        "traffic": "traffic",
        "radar": "site",
    }
    for i, layer in enumerate(LAYER_IDS):
        if layer == "people":
            continue
        dlat = 0.012 * ((i % 5) - 2)
        dlon = 0.016 * ((i // 5) - 1)
        alt = 10_000.0
        if layer in {"satellites", "iss"}:
            alt = 400_000.0
        elif layer in {"vessels", "cameras", "traffic", "sites", "fires", "weather", "radio", "radar", "quakes"}:
            alt = 80.0
        x, y, z = lla_to_ecef(lat + dlat, lon + dlon, alt)
        heading = 35.0 * i
        zone.store.upsert(
            Entity(
                id=f"mark:{layer}",
                cls=cls_of.get(layer, "site"),
                layer=layer,
                label=layer,
                x=x,
                y=y,
                z=z,
                vx=80.0 if layer in {"flights", "military", "vessels", "drones"} else 0.0,
                freshness="live",
                meta={
                    "lat": lat + dlat,
                    "lon": lon + dlon,
                    "alt": alt,
                    "track_deg": heading,
                    "heading_deg": heading,
                    "mag": 5.2,
                },
            )
        )
        zone.layers[layer] = True


def _seed_cluster(zone, lat: float = 39.78, lon: float = -89.65) -> None:
    """Tight city cluster. Spread ≤0.004° so one city nadir holds every mark."""
    from arelis.earth.entity import LAYER_IDS, Entity
    from arelis.earth.frames import lla_to_ecef

    cls_of = {
        "flights": "aircraft",
        "vessels": "vessel",
        "fires": "fire",
        "satellites": "satellite",
        "radio": "rf",
        "iss": "station",
    }
    # Alts stay under the 3 km camera so marks sit in front of the eye.
    specs = (
        ("flights", "hdg0", 0.0000, 0.0000, 1_200.0, 0.0),
        ("flights", "hdg45", 0.0020, 0.0015, 1_400.0, 45.0),
        ("flights", "hdg90", -0.0018, 0.0022, 1_100.0, 90.0),
        ("flights", "hdg180", 0.0012, -0.0024, 1_600.0, 180.0),
        ("vessels", "vessel", 0.0028, -0.0010, 80.0, 70.0),
        ("fires", "fire", -0.0022, 0.0008, 80.0, 0.0),
        ("satellites", "sat", 0.0032, 0.0004, 1_800.0, 0.0),
        ("radio", "radio", -0.0030, -0.0016, 80.0, 0.0),
        ("iss", "iss", 0.0006, 0.0034, 2_000.0, 0.0),
    )
    for layer, tag, dlat, dlon, alt, heading in specs:
        if abs(dlat) > 0.004 or abs(dlon) > 0.004:
            raise ValueError(f"cluster {tag} spread {dlat},{dlon} exceeds 0.004°")
        x, y, z = lla_to_ecef(lat + dlat, lon + dlon, alt)
        zone.store.upsert(
            Entity(
                id=f"cluster:{tag}",
                cls=cls_of[layer],
                layer=layer,
                label=tag,
                x=x,
                y=y,
                z=z,
                freshness="live",
                meta={
                    "lat": lat + dlat,
                    "lon": lon + dlon,
                    "alt": alt,
                    "track_deg": heading,
                    "heading_deg": heading,
                },
            )
        )
    for key in LAYER_IDS:
        zone.layers[key] = key in cls_of


def _set_layers(zone, on: set[str]) -> None:
    from arelis.earth.entity import LAYER_IDS

    for key in LAYER_IDS:
        zone.layers[key] = key in on


def _place_nadir(panel, lat: float, lon: float, alt_m: float) -> None:
    from arelis.earth.frames import EarthCam, apply_earth_cam, earth_spin_jd, lla_to_ecef
    from arelis.physics.runtime import get_system

    system = get_system()
    assert system is not None
    earth = system.nbody.find("Earth")
    assert earth is not None
    jd = earth_spin_jd(system.epoch_jd, system.t)
    eye = lla_to_ecef(lat, lon, alt_m)
    look = lla_to_ecef(lat, lon, 0.0)
    north = lla_to_ecef(min(89.0, lat + 0.25), lon, alt_m)
    up = (north[0] - eye[0], north[1] - eye[1], north[2] - eye[2])
    panel._earth_cam = EarthCam(eye=eye, look=look, up=up)
    apply_earth_cam(panel.cam, (earth.x, earth.y, earth.z), jd, panel._earth_cam)
    if panel._earth_globe_live():
        panel._push_globe_camera()
        panel._sync_earth_globe(force=True)


def _report_paths(paths: list[Path]) -> None:
    print("--- written ---", flush=True)
    for dest in paths:
        if dest.exists():
            pix_note = ""
            try:
                from PySide6.QtGui import QImage

                img = QImage(str(dest))
                if not img.isNull():
                    pix_note = f"  {img.width()}x{img.height()}"
            except Exception:
                pass
            print(f"{dest}  {dest.stat().st_size} bytes{pix_note}", flush=True)
        else:
            print(f"{dest}  MISSING", flush=True)


def _report_cluster(panel, zone) -> None:
    from arelis.physics.runtime import get_system
    from arelis.ui.earth_overlay import entity_world

    system = get_system()
    if system is None:
        print("cluster: no system", flush=True)
        return
    cx, cy = panel.width() * 0.5, panel.height() * 0.5
    print(
        f"cluster nadir_px=({cx:.0f},{cy:.0f}) "
        f"band={getattr(zone.last_view, 'band', None)} "
        f"alt_m={getattr(zone.last_view, 'alt_m', None)} "
        f"n={len(zone.store)} visible={len(zone.visible())}",
        flush=True,
    )
    near = 0
    flights = 0
    for ent in zone.store.all():
        world = entity_world(system, ent)
        proj = panel._proj(world) if world is not None else None
        if proj is None:
            print(f"  {ent.id}  no-proj", flush=True)
            continue
        sx, sy, depth = proj
        dist = ((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5
        if ent.layer == "flights":
            flights += 1
            if dist < min(cx, cy) * 0.45:
                near += 1
        print(
            f"  {ent.id}  layer={ent.layer}  px=({sx:.0f},{sy:.0f})  "
            f"depth={depth:.0f}  dist={dist:.0f}",
            flush=True,
        )
    print(
        f"flights_near_nadir={near}/{flights} "
        f"(dist < 45% of half-frame)",
        flush=True,
    )


def city_cluster_main() -> int:
    """Qt overlay only. Seed a city-band NYC cluster and grab frames."""
    os.environ["PYTEST_CURRENT_TEST"] = "scripts/walk_earth_globe.py::city_cluster"
    os.environ["ARELIS_SOLAR_GL"] = "0"

    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.theme import app_font, load_fonts

    if not rebound_available():
        print("rebound missing", file=sys.stderr)
        return 2

    app = QApplication.instance() or QApplication([])
    app.setFont(app_font(load_fonts()))
    written: list[Path] = []
    written.append(_write_atlas(app))
    written.append(_write_city_atlas(app))

    set_system(None)
    set_earth(None)
    set_system(SolarSystem.from_states(circular_system(), tracers=0))

    solar = SolarPanel()
    solar.resize(1280, 800)
    solar.show()
    solar.raise_()
    _pump(app, 200)

    solar._set_inspect("Earth")
    solar._travel_to("Earth")
    solar._finish_travel()
    _pump(app, 200)

    zone = get_earth()
    if zone is None or not zone.active:
        print("earth zone not active", file=sys.stderr)
        solar.close()
        return 3
    zone.store.clear()
    _seed_cluster(zone, 39.78, -89.65)

    mixed = {"flights", "vessels", "fires", "satellites", "radio", "iss"}
    _place_nadir(solar, 39.78, -89.65, 8_000.0)
    _set_layers(zone, {"flights"})
    solar.update()
    _pump(app, 400)
    written.append(_grab_screen(app, solar, "11-city-flights-cluster.png"))
    print("after 8km flights-only:", flush=True)
    _report_cluster(solar, zone)

    _set_layers(zone, mixed)
    solar.update()
    _pump(app, 400)
    written.append(_grab_screen(app, solar, "11-city-mixed.png"))
    print("after 8km mixed:", flush=True)
    _report_cluster(solar, zone)

    _place_nadir(solar, 39.78, -89.65, 3_000.0)
    _set_layers(zone, {"flights"})
    solar.update()
    _pump(app, 400)
    written.append(_grab_screen(app, solar, "11-city-flights-3km.png"))
    print("after 3km flights-only:", flush=True)
    _report_cluster(solar, zone)

    _set_layers(zone, mixed)
    solar.update()
    _pump(app, 400)
    written.append(_grab_screen(app, solar, "11-city-mixed-3km.png"))
    print("after 3km mixed:", flush=True)
    _report_cluster(solar, zone)

    _report_paths(written)

    solar.close()
    QTimer.singleShot(0, app.quit)
    app.processEvents()
    return 0


def main() -> int:
    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.earth_globe_host import webengine_available
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.solar_gl import prepare_desktop_gl
    from arelis.ui.theme import app_font, load_fonts
    from arelis.ui.window_resize import configure_native_windows

    if not rebound_available():
        print("rebound missing", file=sys.stderr)
        return 2

    prepare_desktop_gl(os.environ)
    configure_native_windows()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([])
    app.setFont(app_font(load_fonts()))
    print(f"webengine_available={webengine_available()}", flush=True)
    _write_atlas(app)

    set_system(None)
    set_earth(None)
    set_system(SolarSystem.from_states(circular_system(), tracers=0))

    solar = SolarPanel()
    solar.resize(1280, 800)
    solar.show()
    solar.raise_()
    _pump(app, 400)
    _grab_screen(app, solar, "01-solar-overview.png")

    solar._set_inspect("Earth")
    _pump(app, 80)
    _grab_screen(app, solar, "02-inspect-earth.png")

    system = get_system()
    if system is not None:
        system.show_lagrange = True
        system.spawn_lagrange("L4")
        _pump(app, 120)
        _grab_screen(app, solar, "02b-solar-lagrange.png")
        system.show_lagrange = False

    solar._travel_to("Earth")
    solar._finish_travel()
    _pump(app, 200)

    host = solar._globe_host
    if host is not None:
        host.bridge.hostFailed.connect(lambda why: print(f"globe failed: {why}", flush=True))
    deadline = time.perf_counter() + 60.0
    while time.perf_counter() < deadline:
        _pump(app, 200)
        if host is not None and (host.ready or host.failed):
            break
        host = solar._globe_host
    _pump(app, 800)
    _grab_screen(app, solar, "06-earth-space.png")
    hud = solar._earth_hud
    print(
        f"globe host={host is not None} ready={getattr(host, 'ready', None)} "
        f"failed={getattr(host, 'failed', None)} kind={getattr(host, 'kind', None)} "
        f"hud={hud is not None and hud.isVisible()}",
        flush=True,
    )

    alts = {
        "space": 3_000_000.0,
        "approach": 800_000.0,
        "near": 80_000.0,
        "city": 8_000.0,
    }
    for name, alt in alts.items():
        _place_nadir(solar, 39.78, -89.65, alt)
        _pump(app, 600)
        _grab_screen(app, solar, f"07-{name}.png")

    zone = get_earth()
    if zone is not None and zone.active:
        _seed_marks(zone)
        _seed_cluster(zone)
        from arelis.earth.entity import LAYER_IDS

        if solar._earth_globe_live():
            solar._sync_earth_globe(force=True)
        for layer in LAYER_IDS:
            if layer == "people":
                continue
            for key in LAYER_IDS:
                zone.layers[key] = key == layer
            if solar._earth_globe_live():
                solar._sync_earth_globe(force=True)
            solar.update()
            _pump(app, 400)
            _grab_screen(app, solar, f"10-layer-{layer}.png")
            host = solar._globe_host
            if host is not None and host._view is not None:
                DEST.mkdir(parents=True, exist_ok=True)
                host._view.grab().save(str(DEST / f"c-layer-{layer}.png"), "PNG")
        for key in LAYER_IDS:
            zone.layers[key] = key != "people"
        if solar._earth_globe_live():
            solar._sync_earth_globe(force=True)
        solar.update()
        _pump(app, 400)
        _grab_screen(app, solar, "10-layer-all.png")
        host = solar._globe_host
        if host is not None and host._view is not None:
            host._view.grab().save(str(DEST / "c-layer-all.png"), "PNG")
        solar._toggle_earth_chip("tiles")
        _pump(app, 800)
        _grab_screen(app, solar, "08-city-streets.png")
        solar._toggle_earth_chip("buildings")
        _pump(app, 800)
        _grab_screen(app, solar, "09-city-buildings.png")
        print(
            f"city tiles={zone.tiles} buildings={zone.buildings} "
            f"band={getattr(zone.last_view, 'band', None)}",
            flush=True,
        )

    pos = QPointF(solar.width() * 0.55, solar.height() * 0.45)
    solar.wheelEvent(
        QWheelEvent(
            pos,
            pos,
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )
    _pump(app, 400)
    _grab_screen(app, solar, "12-earth-wheel.png")

    _key(solar, Qt.Key.Key_H)
    _pump(app, 80)
    _grab_screen(app, solar, "03-help.png")
    _key(solar, Qt.Key.Key_H)

    solar.reset_view()
    _pump(app, 400)
    _grab_screen(app, solar, "15-left-earth.png")

    zone = get_earth()
    print(
        f"left active={zone is not None and zone.active} "
        f"globe_live={solar._earth_globe_live()}",
        flush=True,
    )

    solar.close()
    QTimer.singleShot(0, app.quit)
    app.processEvents()
    return 0


if __name__ == "__main__":
    if "--city-cluster" in sys.argv:
        raise SystemExit(city_cluster_main())
    raise SystemExit(main())
