"""Try to break the Reality plate on camera. Isolated. Not grabWindow(0).

Enter from the Sun (no travel). Leave twice. Mercury kicks Earth.
Re-enter. Find garbage. Ride ISS. Leave.
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

_DATA = Path(tempfile.mkdtemp(prefix="arelis-earth-break-")).resolve()
os.environ["ARELIS_DATA_DIR"] = str(_DATA)
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("ARELIS_ALLOW_OFFSCREEN", None)
os.environ["ARELIS_SOLAR_GL"] = "0"

OUT = ROOT / "outputs" / "earth_reality_break"


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
    _pump(app or top, 150)
    pix = top.grab()
    if pix.isNull() or pix.width() < 40:
        screen = top.screen() or (app.primaryScreen() if app is not None else None)
        if screen is not None:
            pix = screen.grabWindow(int(top.winId()))
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


def main() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.earth_find import apply_goto, close_find, open_find, type_find
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
    panel.setWindowTitle("Arelis Reality break")
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

    shot("01_lab_at_sun")

    # Enter from the Sun. Must not keep looking at the Sun.
    panel._enter_earth_zone()
    _pump(app, 200)
    _wait_globe(app, panel)
    shot("02_enter_from_sun")

    panel._leave_earth_zone()
    panel._leave_earth_zone()
    _pump(app, 200)
    shot("03_double_leave")

    panel._enter_earth_zone()
    _pump(app, 300)
    panel._set_inspect("Mercury")
    _pump(app, 200)
    shot("04_mercury_kicks_earth")

    if system is not None and system.nbody.find("Earth") is not None:
        panel._set_inspect("Earth")
        panel._travel_to("Earth")
        for _ in range(60):
            _pump(app, 40)
            if getattr(panel, "_warp", None) is None:
                break
    panel._enter_earth_zone()
    _pump(app, 200)
    _wait_globe(app, panel)
    shot("05_reenter_earth")

    open_find(panel)
    type_find(panel, "zzzz-not-a-city")
    _pump(app, 150)
    apply_goto(panel)
    _pump(app, 150)
    shot("06_find_miss")
    close_find(panel)

    earth = get_earth()
    if earth is not None and earth.active:
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
        earth.ride("norad:25544")
        panel.update()
        _pump(app, 120)
        shot("07_ride_iss")
        earth.unlock()

    panel._leave_earth_zone()
    _pump(app, 250)
    shot("08_leave_after_abuse")

    panel.hide()
    _pump(app, 150)
    panel.close()
    panel.deleteLater()
    _pump(app, 200)
    set_earth(None)

    if frames:
        try:
            from PIL import Image

            gif = OUT / "break.gif"
            imgs = [Image.open(p).convert("RGB") for p in frames]
            imgs[0].save(
                gif,
                save_all=True,
                append_images=imgs[1:],
                duration=1400,
                loop=0,
            )
            print(f"  video {gif}", flush=True)
        except Exception as exc:
            print(f"  video skipped: {exc}", flush=True)
    print(f"  data {_DATA}", flush=True)
    print(f"  out  {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
