"""HWND walk of the Reality plate. Isolated profile. Not grabWindow(0).

Enter lab → travel to Earth → enter Earth → bands → Find → ride ISS →
leave Earth → leave Reality dump. Writes PNGs + a walk video under
outputs/earth_reality_pass/.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DATA = Path(tempfile.mkdtemp(prefix="arelis-earth-shot-")).resolve()
os.environ["ARELIS_DATA_DIR"] = str(_DATA)
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)
os.environ["ARELIS_SOLAR_GL"] = "0"

OUT = ROOT / "outputs" / "earth_reality_pass"


def _pump(app: Any, ms: int = 80) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.01)


def _grab(top: Any, dest: Path) -> Path:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    from PySide6.QtWidgets import QWidget

    dest.parent.mkdir(parents=True, exist_ok=True)
    top.show()
    top.raise_()
    top.activateWindow()
    app = QGuiApplication.instance()
    _pump(app or top, 200)
    pix = top.grab()
    if pix.isNull() or pix.width() < 40:
        screen = top.screen() or (app.primaryScreen() if app is not None else None)
        if screen is not None:
            pix = screen.grabWindow(int(top.winId()))
    # Cesium host + HUD glass are Tool windows. panel.grab() misses them.
    extras: list[QWidget] = []
    host = getattr(top, "_globe_host", None)
    hud = getattr(top, "_earth_hud", None)
    if isinstance(host, QWidget) and host.isVisible() and getattr(host, "ready", False):
        extras.append(host)
    if isinstance(hud, QWidget) and hud.isVisible():
        extras.append(hud)
    if extras and not pix.isNull():
        composed = QPixmap(pix)
        painter = QPainter(composed)
        try:
            for widget in extras:
                extra = widget.grab()
                if extra.isNull():
                    screen = widget.screen() or (
                        app.primaryScreen() if app is not None else None
                    )
                    if screen is not None:
                        extra = screen.grabWindow(int(widget.winId()))
                if extra.isNull():
                    continue
                gp = widget.mapToGlobal(QPoint(0, 0))
                lp = top.mapFromGlobal(gp)
                painter.drawPixmap(lp, extra)
        finally:
            painter.end()
        pix = composed
    pix.save(str(dest), "PNG")
    print(
        f"  shot {dest.name}  {pix.width()}x{pix.height()}  {dest.stat().st_size} bytes",
        flush=True,
    )
    return dest


def _wait_globe(app: Any, panel: Any, ms: int = 45000) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        _pump(app, 80)
        host = getattr(panel, "_globe_host", None)
        if host is not None and getattr(host, "failed", False):
            return
        if getattr(panel, "_globe_revealed", False):
            _pump(app, 400)
            return


def _pose_band(panel: Any, band: str, lat: float, lon: float, alt_m: float) -> None:
    from arelis.earth.frames import nadir_cam
    from arelis.earth.lod import EarthView
    from arelis.earth.runtime import get_earth
    from arelis.physics.runtime import get_system

    earth = get_earth()
    if earth is None:
        return
    earth.last_view = EarthView(band, alt_m=alt_m, lat=lat, lon=lon, px_r=400.0)
    panel._earth_cam = nadir_cam(lat, lon, alt_m)
    panel._earth_agl_m = float(alt_m)
    panel._earth_hold_t = 0.0
    panel._globe_hpr = (0.0, -90.0)
    system = get_system()
    if system is not None:
        panel._hold_earth_eye(system)
    host = getattr(panel, "_globe_host", None)
    if host is not None and not getattr(host, "failed", False):
        host.push_camera(lat, lon, alt_m, 0.0, -90.0)
    panel.update()


def _wait_alt(app: Any, panel: Any, alt_m: float, ms: int = 8000) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        _pump(app, 80)
        lla = getattr(panel, "_cesium_lla", None)
        if not isinstance(lla, tuple) or len(lla) < 3:
            continue
        got = float(lla[2])
        if got <= 0.0:
            continue
        if abs(got - alt_m) / max(alt_m, 1.0) < 0.35:
            _pump(app, 2000)
            return
    _pump(app, 800)


def main() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.export import dump_on_leave
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.earth_find import close_find, open_find, type_find
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.theme import load_fonts

    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    families = load_fonts()
    app.setFont(QFont(families.get("body") or "Segoe UI", 11))

    if rebound_available():
        set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))

    panel = SolarPanel()
    panel.setWindowTitle("Arelis Reality")
    panel.setFont(app.font())
    panel.resize(1280, 800)
    panel._help = False
    system = get_system()
    if system is not None:
        panel._view_id = id(system)
        panel.reset_view()

    frames: list[Path] = []

    def shot(name: str) -> Path:
        path = _grab(panel, OUT / f"{name}.png")
        frames.append(path)
        return path

    shot("01_reality_lab")

    if system is not None and system.nbody.find("Earth") is not None:
        panel._travel_to("Earth")
        for _ in range(80):
            _pump(app, 50)
            if getattr(panel, "_warp", None) is None:
                break
        panel.update()
        _pump(app, 200)
    shot("02_travel_earth_door")

    panel._enter_earth_zone()
    _pump(app, 200)
    earth = get_earth()
    if earth is None or not earth.active:
        from arelis.earth.runtime import require_earth

        earth = require_earth()
        earth.enter()
        panel._enter_earth_zone()
        _pump(app, 200)
    _wait_globe(app, panel)
    shot("03_enter_earth")

    from arelis.earth.frames import subsolar_lla

    slat, slon = subsolar_lla()
    _pose_band(panel, "space", slat, slon, 20_000_000.0)
    _wait_alt(app, panel, 20_000_000.0)
    shot("04_live_space")

    _pose_band(panel, "approach", 35.68, 139.65, 500_000.0)
    _wait_alt(app, panel, 500_000.0)
    shot("05_live_approach")

    _pose_band(panel, "near", 35.68, 139.65, 50_000.0)
    _wait_alt(app, panel, 50_000.0)
    shot("06_live_near")

    earth.live = True
    _pose_band(panel, "city", 35.68, 139.65, 8_000.0)
    _wait_alt(app, panel, 8_000.0, ms=12000)
    _pump(app, 2500)
    shot("07_live_city")

    open_find(panel)
    type_find(panel, "Tokyo")
    _pump(app, 200)
    shot("08_find_tokyo")
    close_find(panel)

    iss = earth.get("norad:25544")
    if iss is None:
        from arelis.earth.entity import Entity
        from arelis.earth.frames import lla_to_ecef

        x, y, z = lla_to_ecef(0.0, 0.0, 400_000.0)
        earth.store.upsert(
            Entity(
                id="norad:25544",
                cls="station",
                layer="iss",
                label="ISS",
                x=x,
                y=y,
                z=z,
                freshness="live",
            )
        )
        iss = earth.get("norad:25544")
    if iss is not None:
        earth.ride(iss.id)
        panel.update()
        _pump(app, 80)
        shot("09_ride_iss")
        earth.unlock()

    panel._leave_earth_zone()
    _pump(app, 900)
    shot("10_leave_earth")

    dump_on_leave(camera=panel.camera_state())
    shot("11_leave_reality")

    panel.hide()
    _pump(app, 150)
    panel.close()
    panel.deleteLater()
    _pump(app, 200)
    set_earth(None)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg and frames:
        video = OUT / "walk.mp4"
        import subprocess

        lst = OUT / "frames.txt"
        lst.write_text(
            "".join(f"file '{p.as_posix()}'\nduration 1.4\n" for p in frames)
            + f"file '{frames[-1].as_posix()}'\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(lst),
                "-vf",
                "scale=1280:800:force_original_aspect_ratio=decrease,"
                "pad=1280:800:(ow-iw)/2:(oh-ih)/2",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ],
            check=False,
        )
        print(f"  video {video}", flush=True)
    elif frames:
        try:
            from PIL import Image

            gif = OUT / "walk.gif"
            imgs = [Image.open(p).convert("RGB") for p in frames]
            imgs[0].save(
                gif,
                save_all=True,
                append_images=imgs[1:],
                duration=1400,
                loop=0,
            )
            print(f"  video {gif} (ffmpeg missing, gif stitch)", flush=True)
        except Exception as exc:
            print(f"  video skipped: {exc}", flush=True)
    print(f"  data {_DATA}", flush=True)
    print(f"  out  {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
