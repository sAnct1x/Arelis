"""Offscreen Reality HUD shots for the polish loop. Not a Cesium walk."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTEST_CURRENT_TEST", "shot_reality_polish")


def main() -> int:
    from PySide6.QtGui import QFont, QImage
    from PySide6.QtWidgets import QApplication

    from arelis.earth.lod import EarthView
    from arelis.earth.runtime import EarthRuntime, set_earth
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.earth_find import open_find, type_find
    from arelis.ui.panels.solar import SolarPanel

    out = ROOT / "outputs" / "reality-polish"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    from arelis.ui.theme import load_fonts

    families = load_fonts()
    app.setFont(QFont(families.get("body") or "Segoe UI", 11))
    if rebound_available():
        set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.setFont(app.font())
    panel.resize(1280, 800)
    panel._help = False
    system = get_system()
    if system is not None:
        panel._view_id = id(system)
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.last_view = EarthView("space", alt_m=3_000_000.0, px_r=40.0)
    set_earth(earth)
    panel._set_inspect("Earth")

    def grab(name: str) -> Path:
        panel.update()
        app.processEvents()
        image = QImage(panel.size(), QImage.Format.Format_ARGB32)
        image.fill(0xFF160D07)
        panel.render(image)
        path = out / f"{name}.png"
        image.save(str(path))
        print(path)
        return path

    grab("01-enter-simulated-space")
    panel._help = True
    grab("02-keys-earth-marks")
    panel._help = False
    earth.live = True
    earth.last_view = EarthView("city", alt_m=8_000.0, lat=35.68, lon=139.65, px_r=600.0)
    grab("03-live-city")
    open_find(panel)
    type_find(panel, "Tok")
    grab("04-find-tokyo")
    set_earth(None)
    panel.hide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
