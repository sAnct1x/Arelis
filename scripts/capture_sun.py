"""Headless FBO captures of the Sun at inspect / 1 AU / 40 AU."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["ARELIS_SOLAR_GL"] = "1"
os.environ.setdefault("QT_OPENGL", "desktop")
sys.path.insert(0, str(ROOT))

from arelis.ui.solar_gl import prepare_desktop_gl

prepare_desktop_gl(os.environ)

from PySide6.QtWidgets import QApplication

from arelis.physics.constants import AU_M
from arelis.physics.runtime import get_system
from arelis.physics.star_look import star_flare
from arelis.ui.panels.solar import SolarPanel


def _place(panel: SolarPanel, dist_m: float) -> None:
    system = get_system()
    assert system is not None
    sun = system.nbody.find("Sun")
    assert sun is not None
    panel.cam.min_distance = min(dist_m * 0.5, sun.radius * 2.0)
    panel.cam.max_distance = max(panel.cam.max_distance, dist_m * 2.0)
    panel.cam.yaw = 0.35
    panel.cam.pitch = 0.12
    panel.cam.place_looking_at(sun.x, sun.y, sun.z, dist_m)
    panel.cam.look_at(sun.x, sun.y, sun.z)


def main() -> int:
    out = ROOT / "outputs" / "physics" / "solar" / "_look"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    panel = SolarPanel()
    w, h = 1280, 800
    panel.resize(w, h)
    panel._load_kepler_bootstrap()
    system = get_system()
    if system is None:
        print("no system")
        return 1
    system.paused = True
    system.overlay.show_magnetic = False
    panel._ensure_space()
    if panel._gl is None or not panel._gl.gl_ok:
        print("gl_ok=False", panel._gl)
        return 2
    sun = system.nbody.find("Sun")
    assert sun is not None
    shots = (
        ("inspect", 0.04 * AU_M),
        ("1au", 1.0 * AU_M),
        ("40au", 40.0 * AU_M),
    )
    for name, dist in shots:
        _place(panel, dist)
        panel._inspect = "Sun" if name == "inspect" else None
        panel._gl._frame_key = None
        frame = panel._gl.render(w, h)
        if frame is None or frame.isNull():
            print(name, "empty frame")
            return 3
        path = out / f"{name}.png"
        frame.save(str(path))
        from arelis.physics.star_look import angular_px

        disc = angular_px(sun.radius, dist, h, panel._fov_y())
        look = star_flare(disc, h)
        print(
            f"{name}: dist={dist / AU_M:.4f} AU disc={disc:.2f}px "
            f"bloom={look.bloom_px:.1f} spike={look.spike_px:.1f} "
            f"unresolved={look.unresolved:.3f} extent={look.extent_px:.1f} "
            f"cam=({panel.cam.x:.3g},{panel.cam.y:.3g},{panel.cam.z:.3g}) "
            f"-> {path}"
        )
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
