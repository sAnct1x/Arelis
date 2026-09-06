"""Prove the Earth-zone limb ghost the same way a person sees it.

Qt widget.grab() misses a foreign Cesium HWND. This script enters Earth
on the daily-driver path (GPU solar → child Cesium), then
QScreen.grabWindow on the top-level plate — that is the composite.
A magenta sheet sits behind the plate so a transparent hole is obvious.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["ARELIS_SOLAR_GL"] = "1"
if sys.platform == "win32":
    os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QWidget

DEST = ROOT / ".tmp-earth-ghost"
MAGENTA = (255, 0, 255)


def _pump(app: QApplication, ms: int) -> None:
    app.processEvents()
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000 < ms:
        app.processEvents()


def _save(img: QImage, name: str) -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    dest = DEST / name
    img.save(str(dest), "PNG")
    print(f"wrote {dest}  {img.width()}x{img.height()}", flush=True)
    return dest


def _qt_backing(panel) -> QImage:
    img = QImage(panel.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    panel.render(img)
    return img


def _screen_composite(win) -> QImage:
    """Desktop pixels under this window, including foreign child HWNDs."""
    top = win.window()
    screen = top.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return QImage()
    geo = top.frameGeometry()
    full = screen.grabWindow(0)
    if full.isNull():
        return screen.grabWindow(int(top.winId())).toImage()
    return full.copy(geo).toImage()


def _grab_hwnd(hwnd: int) -> QImage:
    screen = QGuiApplication.primaryScreen()
    if screen is None or hwnd <= 0:
        return QImage()
    return screen.grabWindow(int(hwnd)).toImage()


def _magenta_frac(img: QImage) -> float:
    if img.isNull() or img.width() < 8:
        return 0.0
    scaled = img.scaled(160, 100)
    hits = 0
    n = scaled.width() * scaled.height()
    for y in range(scaled.height()):
        for x in range(scaled.width()):
            c = QColor(scaled.pixel(x, y))
            if c.red() > 200 and c.blue() > 200 and c.green() < 80:
                hits += 1
    return hits / max(n, 1)


def _bright_frac(img: QImage, floor: int = 40) -> float:
    if img.isNull() or img.width() < 8:
        return 0.0
    scaled = img.scaled(160, 100)
    bright = 0
    n = scaled.width() * scaled.height()
    for y in range(scaled.height()):
        for x in range(scaled.width()):
            c = QColor(scaled.pixel(x, y))
            if max(c.red(), c.green(), c.blue()) >= floor:
                bright += 1
    return bright / max(n, 1)


def _noon_lon() -> float:
    now = datetime.now(UTC)
    hour = now.hour + now.minute / 60.0 + now.second / 3600.0
    lon = 180.0 - hour * 15.0
    if lon > 180.0:
        lon -= 360.0
    if lon < -180.0:
        lon += 360.0
    return lon


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
    panel._globe_hpr = None
    apply_earth_cam(panel.cam, (earth.x, earth.y, earth.z), jd, panel._earth_cam)
    if panel._earth_globe_live():
        panel._push_globe_camera()
        panel._sync_earth_globe(force=True)


def _place_dayside(panel, alt_m: float) -> None:
    _place_nadir(panel, 15.0, _noon_lon(), alt_m)


def main() -> int:
    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.ui.earth_globe_host import (
        globe_wants_own_process,
        share_group_live,
        webengine_available,
    )
    from arelis.ui.glass import seal_tool_window
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
    app = QApplication.instance() or QApplication([])
    app.setFont(app_font(load_fonts()))

    print(f"webengine={webengine_available()} oop={globe_wants_own_process()}", flush=True)
    set_system(None)
    set_earth(None)

    sheet = QWidget()
    sheet.setObjectName("GhostSheet")
    sheet.setStyleSheet("background:#ff00ff;")
    sheet.resize(1400, 920)
    sheet.move(20, 20)
    sheet.show()
    sheet.lower()

    solar = SolarPanel()
    solar._ensure_ic()
    solar.resize(1280, 800)
    solar.setWindowTitle("probe earth ghost")
    seal_tool_window(solar)
    solar.move(60, 60)
    solar.show()
    solar.raise_()
    solar.activateWindow()
    _pump(app, 400)

    solar._enter_earth_zone()
    _pump(app, 200)

    host = solar._globe_host
    deadline = time.perf_counter() + 70.0
    while time.perf_counter() < deadline:
        _pump(app, 250)
        host = solar._globe_host
        if host is not None and (host.ready or host.failed):
            break

    print(
        f"host={host is not None} ready={getattr(host, 'ready', None)} "
        f"failed={getattr(host, 'failed', None)} kind={getattr(host, 'kind', None)} "
        f"own={getattr(host, '_own_process', None)} hwnd={getattr(host, '_hwnd', None)} "
        f"live={solar._earth_globe_live()} share={share_group_live()}",
        flush=True,
    )
    if host is None or not host.ready:
        print("cesium did not come up", flush=True)
        solar.close()
        sheet.close()
        return 3

    _place_dayside(solar, 12_000_000.0)
    _pump(app, 8000)
    solar.raise_()
    solar.activateWindow()
    _pump(app, 300)

    qt = _qt_backing(solar)
    _save(qt, "01-qt-backing.png")
    screen = _screen_composite(solar)
    _save(screen, "02-screen-space.png")
    child = _grab_hwnd(int(getattr(host, "_hwnd", 0) or 0))
    if not child.isNull():
        _save(child, "03-cesium-hwnd.png")

    _place_nadir(solar, 35.68, 139.65, 8_000.0)
    _pump(app, 5000)
    near = _screen_composite(solar)
    _save(near, "04-screen-tokyo.png")

    qt_bright = _bright_frac(qt)
    sc_bright = _bright_frac(screen)
    near_bright = _bright_frac(near)
    leak = max(_magenta_frac(screen), _magenta_frac(near), _magenta_frac(child))
    print(
        f"qt_bright={qt_bright:.3f} space_bright={sc_bright:.3f} "
        f"near_bright={near_bright:.3f} magenta_leak={leak:.3f} "
        f"noon_lon={_noon_lon():.1f}",
        flush=True,
    )
    zone = get_earth()
    print(f"zone active={zone is not None and zone.active}", flush=True)

    leftover = qt_bright > 0.08
    hole = leak > 0.02
    no_planet = sc_bright < 0.02 and near_bright < 0.02
    print(
        f"verdict leftover_qt_disc={leftover} magenta_hole={hole} "
        f"no_planet={no_planet}",
        flush=True,
    )

    solar.close()
    sheet.close()
    QTimer.singleShot(0, app.quit)
    app.processEvents()
    if leftover or hole or no_planet:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
