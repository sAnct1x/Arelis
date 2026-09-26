"""Live eyes for snapshot/coast tracks and street-distance LOD.

Does not force Streets on. Enter, wait for a published snapshot, then
fly far → close and write what the zone actually did.
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ["ARELIS_SOLAR_GL"] = "1"
if sys.platform == "win32":
    os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

DEST = ROOT / ".tmp-earth-lod"


def _pump(app: QApplication, ms: int) -> None:
    app.processEvents()
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000 < ms:
        app.processEvents()


def _grab(win, name: str) -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    top = win.window()
    top.show()
    top.raise_()
    top.activateWindow()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    screen = top.screen() or QGuiApplication.primaryScreen()
    dest = DEST / name
    if screen is None:
        print(f"no screen for {name}", flush=True)
        return dest
    geo = top.frameGeometry()
    full = screen.grabWindow(0)
    img = full.copy(geo).toImage() if not full.isNull() else screen.grabWindow(int(top.winId())).toImage()
    img.save(str(dest), "PNG")
    print(f"wrote {dest}  {img.width()}x{img.height()}", flush=True)
    return dest


def _place(panel, lat: float, lon: float, alt_m: float) -> None:
    from arelis.earth.frames import EarthCam, apply_earth_cam, earth_spin_jd, lla_to_ecef
    from arelis.earth.lod import view_from_eye
    from arelis.earth.runtime import get_earth
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
    panel._globe_hpr = (0.0, -90.0)
    apply_earth_cam(panel.cam, (earth.x, earth.y, earth.z), jd, panel._earth_cam)
    zone = get_earth()
    if zone is not None:
        zone.note_view(view_from_eye(eye, px_r=800.0, locked=True, look_ecef=look))
        zone.tick(unix=time.time())
    if panel._earth_globe_live():
        host = panel._globe_host
        if host is not None:
            host.fly_to(lat, lon, alt_m)
            host.push_streets(bool(zone.tiles) if zone is not None else False)
        panel._sync_earth_globe(force=True)


def _fresh(zone) -> str:
    vis = list(zone.visible()) if zone is not None else []
    store = list(zone.store.all()) if zone is not None else []
    return (
        f"note={getattr(zone, 'note', None)!r} live={getattr(zone, 'live', None)} "
        f"tiles={getattr(zone, 'tiles', None)} buildings={getattr(zone, 'buildings', None)} "
        f"fetch={sorted((getattr(zone, 'last_fetch_unix', {}) or {}).keys())} "
        f"visible={len(vis)} {dict(Counter(e.freshness for e in vis))} "
        f"store={len(store)} {dict(Counter(e.freshness for e in store))} "
        f"layers={[e.layer for e in vis[:8]]}"
    )


def _note(panel, tag: str) -> None:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    view = getattr(zone, "last_view", None) if zone is not None else None
    print(
        f"{tag} band={getattr(view, 'band', None)} alt={getattr(view, 'alt_m', None)} "
        f"{_fresh(zone)}",
        flush=True,
    )


def main() -> int:
    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.ui.earth_globe_host import webengine_available
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
    print(f"webengine={webengine_available()}", flush=True)

    set_system(None)
    set_earth(None)
    solar = SolarPanel()
    solar._ensure_ic()
    solar.resize(1280, 800)
    solar.setWindowTitle("walk earth lod")
    seal_tool_window(solar)
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
        f"own={getattr(host, '_own_process', None)}",
        flush=True,
    )
    if host is None or not host.ready:
        print("cesium did not come up", flush=True)
        solar.close()
        return 3

    zone = get_earth()
    _note(solar, "enter")
    wait = time.perf_counter() + 25.0
    while time.perf_counter() < wait:
        _pump(app, 400)
        zone = get_earth()
        if zone is not None and zone.last_fetch_unix:
            break
    _note(solar, "after-snapshot")
    _grab(solar, "01-enter.png")

    poses = (
        ("tokyo-80km", 35.68, 139.76, 80_000.0, "02-tokyo-80km.png"),
        ("tokyo-20km", 35.68, 139.76, 20_000.0, "03-tokyo-20km.png"),
        ("tokyo-8km", 35.68, 139.76, 8_000.0, "04-tokyo-8km.png"),
        ("tokyo-2km", 35.68, 139.76, 2_000.0, "05-tokyo-2km.png"),
        ("tokyo-80km-again", 35.68, 139.76, 80_000.0, "06-tokyo-80km-out.png"),
    )
    for tag, lat, lon, alt, name in poses:
        _place(solar, lat, lon, alt)
        _pump(app, 4500)
        solar.update()
        _pump(app, 200)
        _note(solar, tag)
        _grab(solar, name)

    solar.close()
    QTimer.singleShot(0, app.quit)
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
